# Chatbot del dashboard: contesta preguntas sobre los csv de Prefinal/<PSI>/Procesado/ usando un modelo local
# de Ollama (no usa internet ni paga nada).
#
# Como funciona:
#   1. Se le da al modelo la descripcion de las tablas (nombre, columnas y 3 filas de ejemplo), NO todos los datos.
#   2. El modelo escribe codigo de pandas que contesta la pregunta.
#   3. Aqui se corre ese codigo sobre las tablas reales, asi los numeros salen de los datos y no los inventa el modelo.
#   4. El modelo explica el resultado en una frase, en el idioma de la pregunta.
#
# Antes de usarlo: tener Ollama abierto con un modelo instalado (por ejemplo: ollama pull qwen3.5:4b)
# y haber corrido construir_procesados.py (o los exportadores) para que existan los csv.
#
# Uso:
#   py -I -X utf8 chatbot_dataframes.py servidor    -> servidor para el dashboard (POST http://localhost:8000/preguntar)
#   py -I -X utf8 chatbot_dataframes.py             -> chat en la consola
import os
import sys
import re
import glob
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))            # Prefinal/dash
PREFINAL = os.path.dirname(AQUI).replace('\\', '/') + '/'    # Prefinal/ (ahi estan las carpetas PSI-xx/Procesado)
INVESTIGACIONES = ['PSI-25', 'PSI-26', 'PSI-68', 'PSI-69', 'PSI-98', 'PSI-99', 'PSI-100']
OLLAMA_OPCIONES = ['http://localhost:11434']  # se usa la primera que conteste
OLLAMA = OLLAMA_OPCIONES[0]
MODELO = 'qwen3.5:4b'               # el mismo del dashboard; si no esta, se usa el primero que este instalado
ESPERA = 180                        # segundos maximos que se espera cada respuesta del modelo
MAX_TABLAS = 5                      # cuantas tablas se le describen al modelo por pregunta, como maximo
MAX_DESCRIPCION = 10000             # letras maximas de descripcion de tablas (para no pasarse de la memoria del modelo)
PROHIBIDO = ['import', '__', 'open', 'eval', 'exec', 'os', 'sys', 'subprocess', 'to_csv', 'to_excel', 'to_pickle',
             'to_json', 'to_parquet', 'to_sql', 'to_hdf', 'read_csv', 'read_excel', 'read_pickle', 'read_json',
             'input', 'globals', 'locals', 'getattr', 'setattr', 'delattr', 'compile', 'breakpoint']
PERMITIDO = {'len': len, 'range': range, 'min': min, 'max': max, 'sum': sum, 'sorted': sorted, 'abs': abs,
             'round': round, 'list': list, 'dict': dict, 'set': set, 'tuple': tuple, 'str': str, 'int': int,
             'float': float, 'bool': bool, 'enumerate': enumerate, 'zip': zip, 'any': any, 'all': all,
             'isinstance': isinstance}

# Las instrucciones van en ingles porque el dashboard y los datos estan en ingles
INSTRUCCIONES = '''You are an assistant that queries pandas tables. You answer by writing Python code.
Rules:
- The tables are already loaded as variables (t1, t2, ...). pd and np also exist. Do not use import and do not read files.
- Use only the tables and columns that appear in the description, with their exact names.
- The data is not cleaned: if a numeric column comes as text use pd.to_numeric(col, errors='coerce').
- Save the final answer in a variable called resultado (a number, text, Series or DataFrame).
- Reply ONLY with one ```python ... ``` block and nothing else.
- If the question cannot be answered with these tables, set resultado = 'I cannot answer that with these tables'.
- If it is a greeting or it is not a question about the data, set resultado = 'your short reply, in the language of the question'.'''


def llama_ollama(mensajes, modelo):
    # Manda la conversacion a Ollama y regresa el texto de la respuesta.
    # think=False apaga el "modo de pensar" de modelos como qwen3: sin eso tardan minutos y parece que se traba.
    cuerpo = {'model': modelo, 'messages': mensajes, 'stream': False, 'think': False,
              'options': {'temperature': 0, 'num_ctx': 16384}}
    for intento in range(2):
        peticion = urllib.request.Request(OLLAMA + '/api/chat', data=json.dumps(cuerpo).encode('utf-8'),
                                          headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(peticion, timeout=ESPERA) as r:
                texto = json.loads(r.read().decode('utf-8'))['message']['content']
            return re.sub(r'<think>.*?</think>', '', texto, flags=re.S).strip()
        except urllib.error.HTTPError as e:
            if e.code == 400 and 'think' in cuerpo:
                del cuerpo['think']   # modelos que no tienen modo de pensar: se repite sin esa opcion
                continue
            raise


def modelos_instalados():
    # Lista de modelos que tiene Ollama. Regresa None si Ollama no esta corriendo.
    try:
        with urllib.request.urlopen(OLLAMA + '/api/tags', timeout=5) as r:
            return [m['name'] for m in json.loads(r.read().decode('utf-8'))['models']]
    except (urllib.error.URLError, OSError):
        return None


def revisa_modelo(modelo):
    # Busca en que direccion contesta Ollama y avisa si falta el modelo. Regresa el modelo que se va a usar.
    global OLLAMA
    instalados = None
    for direccion in OLLAMA_OPCIONES:
        OLLAMA = direccion
        instalados = modelos_instalados()
        if instalados is not None:
            break
    if instalados is None:
        OLLAMA = OLLAMA_OPCIONES[0]
        print(f'AVISO: Ollama no contesta en {OLLAMA_OPCIONES}. Abrelo antes de preguntar.')
    elif not instalados:
        print(f'AVISO: Ollama no tiene modelos. Baja uno con: ollama pull {modelo}')
    elif modelo not in instalados:
        print(f'AVISO: el modelo "{modelo}" no esta instalado. Uso "{instalados[0]}". Instalados: {instalados}')
        modelo = instalados[0]
    print(f'Ollama: {OLLAMA} | modelo: {modelo}')
    return modelo


def carga_procesados(carpeta=PREFINAL, investigaciones=INVESTIGACIONES):
    # Lee todos los csv de <carpeta>/<PSI>/Procesado/ y regresa {'t1': df, 't2': df, ...}.
    # En df.attrs queda de que investigacion y archivo salio cada tabla.
    # Solo se cargan los csv que muestra el dashboard (los de procesados.js, unos 20): en Procesado hay mas de
    # 15 mil csv y cargarlos todos tarda mucho y llena la memoria. Si no existe procesados.js se cargan todos.
    elegidos = None
    try:
        import json
        texto = open(os.path.join(AQUI, 'procesados.js'), encoding='utf-8').read()
        resumen = json.loads(texto[texto.index('{'):texto.rindex('}') + 1])
        elegidos = {t['file'] for info in resumen.values() for t in info['tables']}
    except Exception as error:
        print('  No se pudo leer procesados.js (se cargan todos los csv):', type(error).__name__)
    tablas = {}
    for inv in investigaciones:
        for ruta in sorted(glob.glob(carpeta + inv + '/Procesado/*.csv')):
            if elegidos is not None and os.path.basename(ruta) not in elegidos:
                continue
            try:
                df = pd.read_csv(ruta, low_memory=False)
            except Exception as error:
                print('  No se pudo leer', ruta, type(error).__name__)
                continue
            archivo = os.path.basename(ruta)
            df.attrs.update(investigacion=inv, archivo=archivo, nombre=f'{inv} | {archivo}')
            tablas[f't{len(tablas) + 1}'] = df
        print(f'  {inv}: {sum(1 for t in tablas.values() if t.attrs["investigacion"] == inv)} csv')
    return tablas


def describe_tabla(alias, df):
    # Texto corto con lo que el modelo necesita saber de una tabla: nombre, tamano, columnas y 3 filas.
    columnas = ', '.join(f'{c!r} ({df[c].dtype})' for c in list(df.columns)[:80])
    ejemplo = df.head(3).iloc[:, :80].to_string(max_colwidth=25)
    return (f'{alias}: {df.attrs.get("nombre", alias)}\n'
            f'  size: {df.shape[0]} rows x {df.shape[1]} columns\n'
            f'  columns: {columnas}\n  first rows:\n{ejemplo}')


def elige_tablas(pregunta, tablas, investigacion=None):
    # Escoge las tablas que se le describen al modelo:
    #   - si viene una investigacion (o la pregunta nombra un PSI-xx), solo las de esa investigacion;
    #   - se ordenan por cuantas palabras de la pregunta salen en su nombre y sus columnas;
    #   - se toman hasta MAX_TABLAS, sin pasarse de MAX_DESCRIPCION letras (siempre va al menos una).
    nombrada = re.search(r'psi[\s-]?(\d+)', pregunta.lower())
    if nombrada:
        investigacion = f'PSI-{nombrada.group(1)}'
    candidatas = [a for a, df in tablas.items() if not investigacion or df.attrs.get('investigacion') == investigacion]
    if not candidatas:
        candidatas = list(tablas)
    palabras = set(re.findall(r'\w{3,}', pregunta.lower()))
    puntos = []
    for alias in candidatas:
        df = tablas[alias]
        texto = (df.attrs.get('nombre', '') + ' ' + ' '.join(str(c) for c in df.columns)).lower()
        puntos.append((sum(p in texto for p in palabras) + 5 * (alias in palabras), alias))
    ordenadas = [alias for _, alias in sorted(puntos, key=lambda x: -x[0])]   # sorted es estable: en empate gana la primera
    usadas, letras = [], 0
    for alias in ordenadas[:MAX_TABLAS]:
        largo = len(describe_tabla(alias, tablas[alias]))
        if usadas and letras + largo > MAX_DESCRIPCION:
            continue
        usadas.append(alias)
        letras += largo
    return usadas


def saca_codigo(texto):
    # Saca el codigo del bloque ```python ... ``` que contesto el modelo.
    bloque = re.search(r'```(?:python)?\s*\n(.*?)```', texto, re.S)
    return (bloque.group(1) if bloque else texto).strip()


def corre_codigo(codigo, tablas, usadas):
    # Corre el codigo del modelo sobre copias de las tablas (no cambia los datos originales) y regresa `resultado`.
    # Como el codigo lo escribe un modelo, no se le permite importar, abrir archivos ni guardar nada.
    sin_textos = re.sub(r'(\'[^\'\n]*\'|"[^"\n]*")', "''", codigo)   # los nombres de columnas no cuentan
    for palabra in PROHIBIDO:
        patron = re.escape(palabra) if palabra == '__' else r'\b' + re.escape(palabra) + r'\b'
        if re.search(patron, sin_textos):
            raise ValueError(f'the code uses something that is not allowed: {palabra}')
    impreso = []   # lo que el codigo imprime con print() se guarda aqui en vez de salir a la pantalla
    permitido = dict(PERMITIDO, print=lambda *cosas, **_: impreso.append(' '.join(str(c) for c in cosas)))
    variables = {'pd': pd, 'np': np, '__builtins__': permitido}
    variables.update({alias: tablas[alias].copy() for alias in usadas})
    exec(codigo, variables)
    if 'resultado' in variables:
        return variables['resultado']
    if impreso:
        return '\n'.join(impreso)   # no guardo `resultado` pero si imprimio algo: eso es la respuesta
    raise ValueError('the code did not save anything in the variable resultado')


def valor_corto(v):
    # Un valor suelto como texto: los decimales con 6 cifras significativas (22.4322 y no 22.43221706443325)
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        v = float(v)
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f'{v:.6g}'
    return str(v)


def a_texto(resultado, filas=20):
    # Convierte el resultado a texto para mostrarlo (las tablas largas se cortan a 20 filas).
    if isinstance(resultado, (pd.DataFrame, pd.Series)):
        texto = resultado.head(filas).to_string(float_format=lambda v: f'{v:.6g}')
        if len(resultado) > filas:
            texto += f'\n... ({len(resultado)} rows in total)'
        return texto
    if isinstance(resultado, dict):   # un valor por linea
        return '\n'.join(f'{k}: {valor_corto(v)}' for k, v in resultado.items())
    if isinstance(resultado, (list, tuple)):
        return ', '.join(valor_corto(v) for v in resultado)
    return valor_corto(resultado)


def preguntar(pregunta, tablas, modelo=MODELO, historial=None, explicar=True, investigacion=None):
    # Funcion principal: contesta una pregunta sobre las tablas.
    #   tablas:        lo que regresa carga_procesados()
    #   historial:     lista de (pregunta, codigo) anteriores, para que el modelo recuerde de que se hablaba
    #   investigacion: 'PSI-68' para preguntar solo sobre las tablas de esa investigacion
    # Regresa un diccionario con 'respuesta' (texto), 'codigo', 'resultado' (objeto de pandas) y 'tablas' usadas.
    usadas = elige_tablas(pregunta, tablas, investigacion)
    if not usadas:
        return {'respuesta': 'There are no extracted CSV tables loaded. Run construir_procesados.py first.',
                'codigo': '', 'resultado': None, 'tablas': []}
    descripcion = '\n\n'.join(describe_tabla(a, tablas[a]) for a in usadas)
    mensajes = [{'role': 'system', 'content': INSTRUCCIONES + '\n\nAvailable tables:\n\n' + descripcion}]
    for p, c in (historial or [])[-3:]:
        mensajes += [{'role': 'user', 'content': str(p)}, {'role': 'assistant', 'content': f'```python\n{c}\n```'}]
    mensajes.append({'role': 'user', 'content': pregunta})

    codigo, error = '', None
    for intento in range(2):   # si el codigo falla, se le ensena el error al modelo y se intenta una vez mas
        try:
            contestacion = llama_ollama(mensajes, modelo)
        except (urllib.error.URLError, OSError) as e:   # incluye cuando se acaba el tiempo de ESPERA
            return {'respuesta': f'I could not reach Ollama at {OLLAMA}. Check that it is running, that the model '
                                 f'"{modelo}" is installed and that it answers in less than {ESPERA} s. Detail: {e}',
                    'codigo': '', 'resultado': None, 'tablas': usadas}
        codigo = saca_codigo(contestacion)
        try:
            resultado = corre_codigo(codigo, tablas, usadas)
            error = None
            break
        except Exception as e:
            error = f'{type(e).__name__}: {e}'
            mensajes += [{'role': 'assistant', 'content': contestacion},
                         {'role': 'user', 'content': f'That code raised this error: {error}\nFix it.'}]
    if error:
        return {'respuesta': f'I could not answer. The code written by the model failed: {error}',
                'codigo': codigo, 'resultado': None, 'tablas': usadas}

    texto = a_texto(resultado)
    respuesta = texto
    if explicar and not isinstance(resultado, str):   # un texto ya es la respuesta: no se pide explicacion
        try:
            frase = llama_ollama([
                {'role': 'system', 'content': 'Answer in the same language as the question, in 1 to 3 sentences, using '
                                              'ONLY the result you are given. Do not invent numbers or add data that '
                                              'is not there. Keep the units exactly as written in the column names; '
                                              'if a number has no unit, do not add one.'},
                {'role': 'user', 'content': f'Question: {pregunta}\n\nResult computed with pandas:\n{texto[:3000]}'}],
                modelo)
            respuesta = frase.strip() + '\n\n' + texto
        except (urllib.error.URLError, OSError):
            pass   # si falla la explicacion, se queda solo el resultado
    if historial is not None:
        historial.append((pregunta, codigo))
    return {'respuesta': respuesta, 'codigo': codigo, 'resultado': resultado, 'tablas': usadas}


def chatbot(tablas, modelo=MODELO):
    # Chat en la consola. Escribe "salir" para terminar, "tablas" para ver la lista y "codigo" para ver el ultimo codigo.
    if not tablas:
        print('AVISO: no hay csv en las carpetas Procesado. Corre primero construir_procesados.py')
    modelo = revisa_modelo(modelo)
    print(f'Chatbot listo con {len(tablas)} tablas. Escribe "salir" para terminar.')
    historial, ultimo = [], ''
    while True:
        try:
            pregunta = input('\nTu: ').strip()
        except EOFError:
            break
        if pregunta.lower() in ('salir', 'exit', 'quit'):
            break
        if pregunta.lower() == 'tablas':
            for alias, df in tablas.items():
                print(f'  {alias}: {df.attrs["nombre"]} ({df.shape[0]} x {df.shape[1]})')
            continue
        if pregunta.lower() == 'codigo':
            print(ultimo)
            continue
        if not pregunta:
            continue
        print('(pensando...)', flush=True)
        r = preguntar(pregunta, tablas, modelo, historial)
        ultimo = r['codigo']
        print(f'\nBot (tablas {", ".join(r["tablas"])}):\n{r["respuesta"]}')


def servidor(tablas, modelo=MODELO, puerto=8000):
    # Servidor local para el dashboard. El dashboard manda  POST http://localhost:8000/preguntar  con el JSON
    #   {"pregunta": "...", "investigacion": "PSI-68" (opcional), "historial": [[pregunta, codigo], ...] (opcional)}
    # y recibe {"respuesta": "...", "codigo": "...", "tablas": ["t14 = PSI-68 | A109D03_3.csv", ...]}.
    # El historial lo guarda el dashboard (no el servidor), asi no se mezclan las platicas de dos personas.
    if not tablas:
        print('AVISO: no hay csv en las carpetas Procesado. Corre primero construir_procesados.py')
    modelo = revisa_modelo(modelo)
    lista = [{'alias': a, 'investigacion': df.attrs['investigacion'], 'archivo': df.attrs['archivo'],
              'filas': int(df.shape[0]), 'columnas': int(df.shape[1])} for a, df in tablas.items()]

    class Manejador(BaseHTTPRequestHandler):
        def responde(self, codigo, cuerpo):
            datos = json.dumps(cuerpo, ensure_ascii=False).encode('utf-8')
            self.send_response(codigo)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')   # para que el dashboard (otro origen) pueda llamar
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Content-Length', str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_OPTIONS(self):
            self.responde(200, {})

        def do_GET(self):   # para probar en el navegador que el servidor esta vivo
            self.responde(200, {'estado': 'ok', 'modelo': modelo, 'tablas': lista})

        def do_POST(self):
            try:
                cuerpo = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode('utf-8'))
                pregunta = str(cuerpo['pregunta']).strip()[:1000]
                investigacion = cuerpo.get('investigacion') or None
                historial = [(str(p)[:1000], str(c)[:3000]) for p, c in (cuerpo.get('historial') or [])[-3:]]
            except Exception:
                self.responde(400, {'error': 'send a JSON like {"pregunta": "..."}'})
                return
            try:
                r = preguntar(pregunta, tablas, modelo, historial, investigacion=investigacion)
            except Exception as error:   # pase lo que pase, el dashboard recibe una respuesta
                r = {'respuesta': f'Something failed on the chatbot server: {type(error).__name__}', 'codigo': '', 'tablas': []}
            self.responde(200, {'respuesta': r['respuesta'], 'codigo': r['codigo'],
                                'tablas': [f'{a} = {tablas[a].attrs["nombre"]}' for a in r['tablas']]})

    print(f'Servidor del chatbot en http://localhost:{puerto}/preguntar  (Ctrl+C para parar)')
    ThreadingHTTPServer(('127.0.0.1', puerto), Manejador).serve_forever()   # 127.0.0.1: solo desde esta computadora


if __name__ == '__main__':  # corre solo si ejecutas este archivo, no cuando lo importas desde otro
    print('Cargando los csv de', PREFINAL + '<PSI>/Procesado/')
    tablas = carga_procesados()
    if len(sys.argv) > 1 and sys.argv[1] == 'servidor':
        servidor(tablas)
    else:
        chatbot(tablas)
