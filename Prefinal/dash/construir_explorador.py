# Prepara la lista de documentos que muestra el Data Explorer del dashboard.
# Recorre los csv de Prefinal/<PSI>/Procesado/ y escribe en dash/explorador/:
#   resumen.js     -> cuantos csv tiene cada investigacion
#   <PSI>.js       -> la lista de csv de esa investigacion: [nombre, filas, columnas]
#   <PSI>_<n>.js   -> los encabezados y las primeras FILAS filas de cada csv, en grupos de GRUPO archivos
# El dashboard se abre como archivo (file://) y asi el navegador no deja leer los csv directo;
# por eso se guarda una muestra de cada uno. El csv completo se abre con el enlace "open full CSV".
# Los datos no se limpian ni se cambian: solo se copian las primeras filas tal como vienen.
#
# Uso (desde cualquier carpeta):  py -I -X utf8 construir_explorador.py
# Volver a correrlo cuando cambien los csv de las carpetas Procesado.
import os
import glob
import json
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))            # Prefinal/dash
PREFINAL = os.path.dirname(AQUI).replace('\\', '/') + '/'    # Prefinal/
INVESTIGACIONES = ['PSI-25', 'PSI-26', 'PSI-68', 'PSI-69', 'PSI-98', 'PSI-99', 'PSI-100']
FILAS = 50    # filas de muestra por csv
GRUPO = 200   # csv por archivo de muestra


def construir_explorador(carpeta, investigaciones):
    salida = carpeta + 'dash/explorador/'
    os.makedirs(salida, exist_ok=True)
    for viejo in glob.glob(salida + '*.js'):  # se quita lo de la corrida anterior
        os.remove(viejo)

    def escribe(nombre, variable, clave, datos):
        # Cada archivo .js agrega su parte a una variable global del navegador
        texto = json.dumps(datos, ensure_ascii=False, separators=(',', ':'))
        with open(salida + nombre, 'w', encoding='utf-8') as f:
            f.write(f'window.{variable} = window.{variable} || {{}};\nwindow.{variable}[{json.dumps(clave)}] = {texto};\n')

    resumen = {}
    for psi in investigaciones:
        rutas = sorted(glob.glob(carpeta + psi + '/Procesado/*.csv'), key=lambda r: os.path.basename(r).lower())
        lista, muestras = [], []
        for ruta in rutas:
            try:
                # header=None: la primera fila son los nombres de columna, tal como estan escritos en el csv
                tabla = pd.read_csv(ruta, header=None, dtype=str, keep_default_na=False, encoding='utf-8')
            except Exception:
                tabla = pd.DataFrame()  # csv vacio o que no se pudo leer: queda en la lista con 0 filas
            columnas = tabla.iloc[0].tolist() if len(tabla) else []
            filas = tabla.iloc[1:1 + FILAS].values.tolist()
            lista.append([os.path.basename(ruta), max(len(tabla) - 1, 0), len(columnas)])
            muestras.append({'c': columnas, 'r': filas})
        for n in range(0, len(muestras), GRUPO):
            escribe(f'{psi}_{n // GRUPO}.js', 'EXPLORER_CHUNKS', f'{psi}_{n // GRUPO}', muestras[n:n + GRUPO])
        escribe(f'{psi}.js', 'EXPLORER_INDEX', psi, lista)
        resumen[psi] = {'files': len(lista), 'folder': f'../{psi}/Procesado/'}
        print(psi, len(lista), 'csv')

    with open(salida + 'resumen.js', 'w', encoding='utf-8') as f:
        f.write('window.EXPLORER_SUMMARY = ' + json.dumps({'preview_rows': FILAS, 'group': GRUPO, 'investigations': resumen}) + ';\n')
    print('Listo:', sum(r['files'] for r in resumen.values()), 'csv en', salida)


if __name__ == '__main__':
    construir_explorador(PREFINAL, INVESTIGACIONES)
