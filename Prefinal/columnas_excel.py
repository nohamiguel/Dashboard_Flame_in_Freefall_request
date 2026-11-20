# Lee los Excel (.xls / .xlsx) de data/raw y regresa una lista de DataFrames, uno por cada tabla real de cada hoja.
# Mismo estilo que columnas_csv_simple.py. Reglas probadas en las 93 hojas de las 7 investigaciones base (93/93 bien)
# y revisadas en las demas carpetas (reglas de respaldo A-G, ver README_CONTINUAR.md).
import glob
import os
import re
import sys
import datetime
import warnings
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from columnas_csv_simple import es_tabla  # para los .xls que en realidad son texto

warnings.filterwarnings('ignore')  # avisos de pandas/openpyxl al leer formatos viejos; no afectan

CARPETA = 'C:/Users/noego/Desktop/SpaceApp/Prefinal/'
INVESTIGACIONES = ['PSI-25','PSI-26','PSI-68','PSI-69','PSI-98','PSI-99','PSI-100']  # las 7 base
SALTAR = ['Planned_Test Matrix']  # PSI-26: trae credenciales, no se abre
CHARS_NUM = set('0123456789.,:;+-eE /%')
RESUMEN = re.compile(r'\s*(average|avg|mean|std|stdev|standard deviation|sum|total|ion offset)\b', re.I)  # filas de resumen


def es_numero(v):
    if isinstance(v, (bool, np.bool_, int, float, np.integer, np.floating, datetime.datetime, datetime.date,
                      datetime.time, pd.Timestamp, pd.Timedelta)):
        return True
    s = str(v).strip()
    return any(ch.isdigit() for ch in s) and all(ch in CHARS_NUM for ch in s)


def limpia(df):
    # strings sin espacios de mas; '' -> NaN
    df = df.copy()
    for c in df.columns:
        if not (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c])):
            df[c] = df[c].astype(object).map(lambda v: (v.strip() or np.nan) if isinstance(v, str) else v)
    return df


def nombre(v):
    return re.sub(r'\s+', ' ', str(v)).strip()


def bloques_columnas(m):
    # columnas separadas por columnas totalmente vacias
    llenas = m.any(axis=0)
    bloques, ini = [], None
    for c, x in enumerate(list(llenas) + [False]):
        if x and ini is None:
            ini = c
        elif not x and ini is not None:
            bloques.append((ini, c - 1))
            ini = None
    return bloques


def es_nota(vals):
    # fila con una sola celda de texto de 2+ palabras (titulo, nota, comentario)
    return len(vals) == 1 and isinstance(vals[0], str) and not es_numero(vals[0]) and len(vals[0].split()) >= 2


def busca_encabezado(df, m, c0, c1, limite=60):
    # El encabezado es la fila (de las primeras 60) con MAS celdas de texto (no numero); si empatan, la primera.
    # Si esa fila es mas de la mitad numeros, la tabla no tiene encabezado (-1).
    filas = min(len(df), limite)
    mejor, mejor_n = None, 0
    for r in range(filas):
        vals = [v for v in df.iloc[r, c0:c1 + 1] if pd.notna(v)]
        texto = sum(1 for v in vals if isinstance(v, str) and not es_numero(v) and len(v) <= 120)
        if texto > mejor_n:
            mejor, mejor_n = r, texto
    if mejor is None:
        vals = [v for v in df.iloc[:filas, c0:c1 + 1].values.ravel() if pd.notna(v)]
        return -1 if vals else None
    return mejor


def fila_unidades(df, m, r, c0, c1, ancho_enc):
    if r + 2 >= len(df):
        return False
    vals = [v for v in df.iloc[r, c0:c1 + 1] if pd.notna(v)]
    if not vals or len(vals) < 0.2 * ancho_enc:
        return False
    sig = [v for v in df.iloc[r + 1, c0:c1 + 1] if pd.notna(v)]
    sig_numeros = bool(sig) and sum(es_numero(v) for v in sig) > len(sig) / 2
    if not any(es_numero(v) or not isinstance(v, str) or len(v) > 12 for v in vals):
        return sig_numeros
    # respaldo (G): unidades un poco mas largas ('25 C / 1 atm', 'Correction Factor'): 3+ celdas,
    # 70 % o mas texto corto (<= 25 letras) y abajo puros numeros
    cortos = sum(1 for v in vals if isinstance(v, str) and not es_numero(v) and len(v) <= 25)
    return len(vals) >= 3 and cortos >= 0.7 * len(vals) and sig_numeros


def fila_vacia(m, r, c0, c1):
    return r < 0 or r >= len(m) or not m[r, c0:c1 + 1].any()


def encabezados_repetidos(df, m, h, c0, c1):
    # (B) tablas apiladas: una fila mas abajo que repite el encabezado (60 % o mas de sus celdas iguales, sin numeros)
    # despues de una fila vacia (o de fila vacia + un titulo de 1 celda) empieza otra tabla.
    # Regresa [(fila_encabezado_nueva, fila_donde_termina_la_anterior)]
    nombres_h = {c: nombre(df.iat[h, c]) for c in range(c0, c1 + 1) if m[h, c]}
    if len(nombres_h) < 2:
        return []
    cortes = []
    for r in range(h + 2, len(df)):
        cols_r = [c for c in range(c0, c1 + 1) if m[r, c]]
        if len(cols_r) < 2 or any(es_numero(df.iat[r, c]) for c in cols_r):
            continue
        iguales = sum(1 for c in cols_r if nombres_h.get(c) == nombre(df.iat[r, c]))
        if iguales < max(2, 0.6 * len(cols_r)):
            continue
        if fila_vacia(m, r - 1, c0, c1):
            cortes.append((r, r))
        elif m[r - 1, c0:c1 + 1].sum() == 1 and fila_vacia(m, r - 2, c0, c1):
            cortes.append((r, r - 1))  # el titulo de arriba no es dato de la tabla anterior
    return cortes


def encabezado_es_dato(df, m, h, c0, c1):
    # (I) si el encabezado trae numeros y la mitad o mas de sus celdas vuelven a salir 3+ veces en su misma columna,
    # no son nombres sino datos (bitacora / log sin encabezado). Un encabezado sin numeros que se repite
    # es el de tablas apiladas (regla B), ese si es encabezado.
    cols = [c for c in range(c0, c1 + 1) if m[h, c]]
    if len(cols) < 2 or not any(es_numero(df.iat[h, c]) for c in cols):
        return False
    repetidas = 0
    for c in cols:
        abajo = df.iloc[h + 1:, c].dropna()
        if (abajo.map(nombre) == nombre(df.iat[h, c])).sum() >= 3:
            repetidas += 1
    return repetidas >= 0.5 * len(cols)


def arma_tabla(df, m, h, c0, c1, fin):
    # Arma la tabla con encabezado en la fila h y datos hasta la fila fin (sin incluirla)
    enc = df.iloc[h, c0:c1 + 1]
    ancho_enc = enc.notna().sum()
    unidades = fila_unidades(df, m, h + 1, c0, c1, ancho_enc)
    ini = h + 2 if unidades else h + 1
    cols = [c for c in range(c0, c1 + 1) if m[h, c] or m[ini:fin, c].any()]
    # fila de grupos abajo del encabezado (pocas celdas, solo texto): no es dato
    if not unidades and ini < fin:
        v = [x for x in df.iloc[ini, c0:c1 + 1] if pd.notna(x)]
        if v and len(v) < 0.25 * ancho_enc and not any(es_numero(x) for x in v):
            ini += 1
    nombres = []
    for c in cols:
        n = nombre(df.iat[h, c]) if m[h, c] else f'Unnamed: {c}'
        if unidades and m[h + 1, c]:
            n = f'{n} ({nombre(df.iat[h + 1, c])})'
        nombres.append(n)
    # (A) fila de grupos ARRIBA del encabezado (2+ celdas, puro texto): da nombre a las columnas que no tienen
    # y se pone enfrente de los nombres repetidos ('IPSU1/HiBMS Archived Images', 'FOMA Resources Diluent')
    arriba = h - 1
    if arriba >= 0:
        va = [df.iat[arriba, c] for c in range(c0, c1 + 1) if m[arriba, c]]
        # (debe tener etiquetas en al menos 15 % del ancho del encabezado; si son 1 o 2 sueltas, no se usan)
        if len(va) >= max(2, 0.15 * ancho_enc) and all(isinstance(v, str) and not es_numero(v) and len(v) <= 120 for v in va):
            grupo, g = {}, None
            for c in range(c0, c1 + 1):
                if m[arriba, c]:
                    g = nombre(df.iat[arriba, c])
                grupo[c] = g
            repetidos = {n for n in nombres if nombres.count(n) > 1 and not n.startswith('Unnamed')}
            pares = [(grupo[c], n) for c, n in zip(cols, nombres)]
            nuevos = list(nombres)
            for k, c in enumerate(cols):
                if not m[h, c] and m[arriba, c]:
                    nuevos[k] = nombre(df.iat[arriba, c])
                elif nombres[k] in repetidos and grupo[c] and grupo[c] != nombres[k] and pares.count(pares[k]) == 1:
                    # solo si el grupo sirve para distinguir (en el mismo grupo no se repite el nombre)
                    nuevos[k] = f'{grupo[c]} {nombres[k]}'
            nombres = nuevos
    datos = df.iloc[ini:fin, cols]
    md = m[ini:fin][:, cols]
    n_fila = md.sum(axis=1)
    keep = n_fila > 0
    # 4. quita notas (una celda de texto con 2+ palabras) si la tabla tiene 3+ columnas
    if len(cols) >= 3:
        for i in np.nonzero(keep)[0]:
            vals = [v for v in datos.iloc[i] if pd.notna(v)]
            if es_nota(vals):
                keep[i] = False
    # 5. quita sub-encabezados (filas sin numeros) si casi todo es numero
    vals_all = datos.values[md]
    if len(vals_all):
        muestra = vals_all[:: max(1, len(vals_all) // 5000)]
        frac_num = np.mean([es_numero(v) for v in muestra])
        if frac_num > 0.8:
            for i in np.nonzero(keep)[0]:
                vals = [v for v in datos.iloc[i] if pd.notna(v)]
                if not any(es_numero(v) for v in vals):
                    keep[i] = False
                elif any(isinstance(v, str) and RESUMEN.match(v) for v in vals):
                    keep[i] = False  # (H) fila de resumen metida entre los datos ('average', 'ion offset')
    # 6. basura al final: filas ralas (< 25 % del ancho) con valores casi constantes
    idx = np.nonzero(keep)[0]
    if len(idx):
        j = len(idx)
        while j > 0 and n_fila[idx[j - 1]] <= 0.25 * len(cols):
            j -= 1
        cola = idx[j:]
        if len(cola) >= 2:
            bloque = datos.iloc[cola]
            if all(bloque[c].value_counts(normalize=True).max() >= 0.5 for c in bloque.columns if bloque[c].notna().any()):
                keep[cola] = False
    t = datos[keep].copy()
    t.columns = nombres
    t = t.reset_index(drop=True)
    return t, dict(fila_encabezado=h, filas_encabezado=2 if unidades else 1, c0=c0, c1=c1)


def tablas_hoja(df):
    df = limpia(df)
    m = df.notna().values
    salida = []
    if not m.any():
        return salida
    # 1. bloques de columnas y encabezado de cada uno
    bl = []
    for c0, c1 in bloques_columnas(m):
        h = busca_encabezado(df, m, c0, c1)
        if h is not None and h >= 0 and encabezado_es_dato(df, m, h, c0, c1):
            h = -1
        bl.append([c0, c1, h])
    # 2. junta bloques vecinos con el mismo renglon de encabezado y sin nombres repetidos.
    #    (C) no se juntan si el segundo bloque empieza con una columna que solo es etiqueta (nombre sin datos abajo,
    #    como 'O3 = 0.0 mol.%'): es otra tabla
    juntos = []
    for b in bl:
        if juntos and b[2] is not None and b[2] >= 0 and juntos[-1][2] == b[2]:
            a = juntos[-1]
            n_a = set(nombre(v) for v in df.iloc[b[2], a[0]:a[1] + 1] if pd.notna(v))
            n_b = set(nombre(v) for v in df.iloc[b[2], b[0]:b[1] + 1] if pd.notna(v))
            etiqueta = (m[b[2], b[0]] and not m[b[2] + 1:, b[0]].any()  # primera columna: nombre sin datos
                        and b[1] > b[0] and m[b[2] + 1:, b[0] + 1:b[1] + 1].any())  # y el resto del bloque si trae datos
            # se juntan si no repiten nombres, o si repiten pocos (menos de la mitad del bloque mas chico)
            pocos = len(n_a & n_b) < 0.5 * min(len(n_a), len(n_b))
            if (not (n_a & n_b) or pocos) and not etiqueta:
                a[1] = b[1]
                continue
        juntos.append(list(b))
    for c0, c1, h in juntos:
        if h is None:
            continue
        if h < 0:
            # (F) bloque sin encabezado (puros numeros): se regresa con columnas 0, 1, 2... para reportarlo aparte
            filas = np.nonzero(m[:, c0:c1 + 1].any(axis=1))[0]
            t = df.iloc[filas, c0:c1 + 1].reset_index(drop=True)
            t.columns = list(range(t.shape[1]))
            salida.append((t, dict(fila_encabezado=None, filas_encabezado=0, c0=c0, c1=c1, sin_encabezado=True)))
            continue
        # 2b. tabla chica apilada arriba del encabezado (encabezado de texto + fila con valores)
        for r in range(h - 1):
            v1 = [v for v in df.iloc[r, c0:c1 + 1] if pd.notna(v)]
            cols1 = [c for c in range(c0, c1 + 1) if m[r, c]]
            if len(v1) >= 3 and not any(es_numero(v) or ':' in str(v) for v in v1):
                v2 = [df.iat[r + 1, c] for c in cols1 if m[r + 1, c]]
                if len(v2) >= 0.5 * len(v1) and any(es_numero(v) for v in v2) and not m[r + 2, c0:c1 + 1].any():
                    t = pd.DataFrame([[df.iat[r + 1, c] for c in cols1]], columns=[nombre(df.iat[r, c]) for c in cols1])
                    salida.append((t, dict(fila_encabezado=r, filas_encabezado=1, c0=cols1[0], c1=cols1[-1])))
        # 3-6. la tabla (o las tablas apiladas, si el encabezado se repite mas abajo despues de una fila vacia)
        cortes = encabezados_repetidos(df, m, h, c0, c1)
        inicios = [h] + [r for r, _ in cortes]
        finales = [f for _, f in cortes] + [len(df)]
        for hi, fin in zip(inicios, finales):
            salida.append(arma_tabla(df, m, hi, c0, c1, fin))
    return salida


def es_tabla_de_datos(tabla):
    # Una tabla cuenta solo si tiene 2+ columnas con nombre y 1+ fila de datos (los bloques de calculo,
    # constantes 'nombre: valor' y hojas de notas no cuentan)
    con_nombre = [c for c in tabla.columns if not str(c).startswith('Unnamed')]
    if len(con_nombre) < 2 or len(tabla) < 1:
        return False
    primera = tabla.iloc[:, 0].dropna()
    if str(tabla.columns[0]).startswith('Unnamed') and len(primera) and primera.map(lambda v: isinstance(v, str)).all():
        # primera columna sin nombre con puras etiquetas: calculadora (como ACMEFlowCalculator).
        # (D) solo si es chica o casi no tiene numeros; una tabla grande de mediciones no es calculadora
        vals = tabla.values[tabla.notna().values]
        frac_num = np.mean([es_numero(v) for v in vals]) if len(vals) else 0
        if len(tabla) < 10 or frac_num < 0.5:
            return False
    # (E) plantilla sin datos: 5+ filas y todas iguales (formulas que repiten el mismo valor)
    if len(tabla) >= 5 and len(tabla.astype(str).drop_duplicates()) == 1:
        return False
    return True


def tablas_libro(hojas):
    # Recibe {hoja: DataFrame leido con header=None} y regresa:
    #   tablas: [(hoja, tabla, info)], falsos: [hojas sin tabla de datos], sin_encabezado: [(hoja, tabla, info)]
    tablas, falsos, sin_encabezado = [], [], []
    for hoja, df in hojas.items():
        encontradas = 0
        for tabla, info in tablas_hoja(df):
            if info.get('sin_encabezado'):
                if tabla.shape[0] >= 5 and tabla.shape[1] >= 2:
                    sin_encabezado.append((str(hoja), tabla, info))
                    encontradas += 1
                continue
            if es_tabla_de_datos(tabla):
                tablas.append((str(hoja), tabla, info))
                encontradas += 1
        if not encontradas:
            falsos.append(str(hoja))
    return tablas, falsos, sin_encabezado


def tablas_texto(ruta):
    # Algunos .xls en realidad son texto (separado por tabs): se leen con el lector de txt/csv.
    # Igual que en columnas_csv: si no trae encabezados (columnas 0, 1, 2...) va a la lista sin_encabezado.
    texto = open(ruta, 'rb').read().decode('utf-8-sig', errors='replace')
    si, tabla = es_tabla(texto)
    if not si:
        return [], ['(texto)'], []
    if not any(isinstance(c, str) and c != '' for c in tabla.columns):
        return [], [], [('(texto)', tabla, {'fila_encabezado': None, 'sin_encabezado': True})]
    return [('(texto)', tabla, {'fila_encabezado': None})], [], []


def columnas_excel(carpeta, investigaciones):
    # Junta los .xls y .xlsx de las investigaciones, lee cada hoja con pandas y saca sus tablas con tablas_libro().
    # Regresa una lista de DataFrames (una por tabla), con df.attrs['archivo'], ['hoja'], ['investigacion'] y ['fila_encabezado'].
    # Las hojas sin tabla de datos (calculadoras, notas, graficas, vacias) se imprimen como False, y las tablas
    # sin encabezados se imprimen aparte y no se agregan (igual que en columnas_csv).
    archivos = []
    for inv in investigaciones:
        print(inv)
        for ruta in glob.glob(os.path.join(carpeta + inv + '/**/*'), recursive=True):
            
            nombre_archivo = os.path.basename(ruta)
            if not ruta.lower().endswith(('.xls', '.xlsx', '.xlsm')) or not os.path.isfile(ruta):
                continue
            if nombre_archivo.startswith('~$') or any(s in nombre_archivo for s in SALTAR):
                continue  # temporales de Excel y archivos que no se deben abrir
            archivos.append((inv, ruta))
    print('Archivos Excel a revisar:', len(archivos))

    tablas, falsos, sin_encabezados, errores = [], [], [], []
    for inv, ruta in archivos:
        rel = os.path.relpath(ruta, carpeta)
        try:
            hojas = pd.read_excel(ruta, sheet_name=None, header=None)
        except Exception:
            hojas = None  # no se pudo leer como Excel: puede ser texto
        try:
            if hojas is None:
                encontradas, sin_tabla, sin_enc = tablas_texto(ruta)
            else:
                encontradas, sin_tabla, sin_enc = tablas_libro(hojas)
        except Exception as error:
            errores.append(f'{rel} ({type(error).__name__})')
            continue
        for hoja, tabla, info in encontradas:
            tabla.attrs.update(archivo=rel, hoja=hoja, investigacion=inv, fila_encabezado=info['fila_encabezado'])
            tablas.append([tabla,nombre_archivo])
        falsos += [f'{rel} | hoja {hoja}' for hoja in sin_tabla]
        sin_encabezados += [f'{rel} | hoja {hoja} ({t.shape[0]} filas x {t.shape[1]} columnas)' for hoja, t, _ in sin_enc]

    print('Tablas encontradas:', len(tablas))
    print('Tablas sin encabezados (no se agregan):', len(sin_encabezados))
    for s in sin_encabezados:
        print('  Sin encabezados ->', s)
    print('Hojas False (sin tabla de datos):', len(falsos))
    for f in falsos:
        print('  False ->', f)
    print('No se pudieron leer:', len(errores))
    for e in errores:
        print('  Error ->', e)
    return tablas

if __name__ == '__main__':  # corre solo si ejecutas este archivo, no cuando lo importas desde otro
    tablas = columnas_excel(CARPETA, INVESTIGACIONES)
    usados = {}
    for tabla, _ in tablas:  # cada elemento es [tabla, nombre_archivo]: la tabla va primero
        # carpeta de salida de ESA investigacion: Prefinal/PSI-98/Procesado/, Prefinal/PSI-100/Procesado/...
        ruta_salida = CARPETA + tabla.attrs['investigacion'] + '/Procesado/'
        os.makedirs(ruta_salida, exist_ok=True)  # crea la carpeta si no existe
        # nombre del csv: archivo (sin .xlsx) + hoja; si una hoja trae varias tablas se numeran _2, _3...
        base = os.path.splitext(os.path.basename(tabla.attrs['archivo']))[0] + '_' + str(tabla.attrs['hoja'])
        base = re.sub(r'[\\/:*?"<>|]', '_', base)  # caracteres que Windows no deja en nombres de archivo
        usados[ruta_salida + base] = usados.get(ruta_salida + base, 0) + 1
        if usados[ruta_salida + base] > 1:
            base += f'_{usados[ruta_salida + base]}'
        tabla.to_csv(ruta_salida + base + '.csv', index=False)
    print('CSV guardados:', len(tablas))
