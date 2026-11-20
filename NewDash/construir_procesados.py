# Prepara los datos extraidos que muestra el dashboard y que consulta el chatbot.
#   1. De cada investigacion se corre UN solo archivo (el de la lista ELEGIDOS) con los mismos lectores de
#      columnas_excel.py y columnas_csv_simple.py, y sus tablas se guardan como csv en Prefinal/<PSI>/Procesado/.
#   2. Se hace un resumen de cada csv (filas, columnas, minimo, maximo, promedio...) y se escribe en
#      dash/procesados.js, que es lo que lee el dashboard para la tarjeta "Extracted data" de cada experimento.
# Los datos no se limpian ni se cambian: el resumen solo los describe.
#
# Uso (desde cualquier carpeta):  py -I -X utf8 construir_procesados.py
# Volver a correrlo si se cambia un archivo de ELEGIDOS.
import os
import re
import sys
import json
import warnings
import urllib.parse
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))            # Prefinal/dash
PREFINAL = os.path.dirname(AQUI).replace('\\', '/') + '/'    # Prefinal/
sys.path.insert(0, PREFINAL)                                 # para importar los lectores (con py -I no se agrega sola)
from columnas_excel import tablas_libro, tablas_texto
from columnas_csv_simple import es_tabla, separar, RAYA, LIMITE

warnings.filterwarnings('ignore')

# Un archivo por investigacion (ruta desde la carpeta de la investigacion). Para mostrar otro, se cambia aqui.
ELEGIDOS = {
    'PSI-25': 'Science Documents/PSI-25_Science Documents_BASS-II_Test.Matrices.xlsx',
    'PSI-26': 'Science Documents/PSI-26_Science Documents_As Run_Test Matrix.xlsx',
    'PSI-68': 'Raw Data/Legacy/A109D03/A109D03.txt',
    'PSI-69': 'Raw Data/Reduced Gravity/MeOH_Air/Flex-002/PSI-69_Raw Data_Test 002 Results.xls',
    'PSI-98': 'Raw Data/Reduced Gravity/S1 Data Package Sensor Telemetry/PSI-98_Raw Data_Saffire-I Sample 1 Sensor Data Complete TM graphs.xlsx',
    'PSI-99': 'Raw Data/Reduced Gravity/Data Package Sensor Telemetry/SAFFIRE_II_S1/PSI-99_Raw Data_Saffire Sensor Data Sample 1.xlsx',
    'PSI-100': 'Raw Data/Reduced Gravity/Data Package Sensor Telemetry/S1/PSI-100_Raw Data_Saffire III Sample 1 Sensors.xlsx',
}
SALTAR = ['Planned_Test Matrix']  # PSI-26: trae credenciales, no se abre
FILAS_MUESTRA = 5                 # filas de ejemplo que se guardan para la tarjeta


def tablas_de_archivo(ruta):
    # Regresa [(nombre_del_csv, tabla)] de un solo archivo, con los mismos nombres que usan los exportadores:
    # Excel -> archivo_hoja (y _2, _3 si la hoja trae varias tablas); txt/csv -> archivo (o _1, _2, _3 si son partes)
    base = os.path.splitext(os.path.basename(ruta))[0]
    salida = []
    if ruta.lower().endswith(('.xls', '.xlsx', '.xlsm')):
        try:
            hojas = pd.read_excel(ruta, sheet_name=None, header=None)
        except Exception:
            hojas = None  # no se pudo leer como Excel: puede ser texto
        encontradas = tablas_texto(ruta)[0] if hojas is None else tablas_libro(hojas)[0]
        usados = {}
        for hoja, tabla, _ in encontradas:
            nombre = re.sub(r'[\\/:*?"<>|]', '_', f'{base}_{hoja}')
            usados[nombre] = usados.get(nombre, 0) + 1
            salida.append((nombre + (f'_{usados[nombre]}' if usados[nombre] > 1 else ''), tabla))
    else:
        texto = open(ruta, 'rb').read().decode('utf-8-sig', errors='replace')
        if RAYA.search(texto[:LIMITE]):
            tablas = separar(texto)
        else:
            si, tabla = es_tabla(texto)
            tablas = [tabla] if si else []
        for i, tabla in enumerate(tablas, start=1):
            salida.append((f'{base}_{i}' if len(tablas) > 1 else base, tabla))
    return salida


def corto(v):
    # Numero corto para mostrar: los enteros quedan exactos y los decimales con 5 cifras significativas
    if isinstance(v, float):
        return int(v) if v.is_integer() and abs(v) < 1e15 else float(f'{v:.5g}')
    return v


def resume_columna(nombre, col):
    # Describe una columna sin cambiarla: cuantas celdas tiene llenas y, segun el tipo, minimo/maximo/promedio,
    # primer y ultimo momento, o los valores de texto mas repetidos
    llenas = col.dropna()
    llenas = llenas[llenas.astype(str).str.strip() != '']
    info = {'name': str(nombre), 'filled': int(len(llenas))}
    if not len(llenas):
        info['type'] = 'empty'
        return info
    numeros = pd.to_numeric(llenas, errors='coerce')
    if numeros.notna().sum() >= 0.8 * len(llenas):
        numeros = numeros.dropna()
        info.update(type='number', min=corto(float(numeros.min())), max=corto(float(numeros.max())),
                    mean=corto(float(numeros.mean())))
        return info
    textos = llenas.astype(str)
    if textos.str.contains(r'\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}:\d{2}', regex=True).mean() >= 0.8:
        fechas = pd.to_datetime(textos, errors='coerce', format='mixed')
        if fechas.notna().sum() >= 0.8 * len(llenas):
            info.update(type='date/time', min=str(fechas.min()), max=str(fechas.max()))
            return info
    cuenta = textos.value_counts()
    info.update(type='text', distinct=int(len(cuenta)), top=[str(v)[:40] for v in cuenta.index[:3]])
    return info


def resume_tabla(archivo, tabla, liga):
    columnas = [resume_columna(c, tabla.iloc[:, i]) for i, c in enumerate(tabla.columns)]
    celdas = tabla.shape[0] * tabla.shape[1]
    llenas = sum(c['filled'] for c in columnas)
    tipos = [c['type'] for c in columnas]
    muestra = tabla.head(FILAS_MUESTRA).astype(object).where(tabla.head(FILAS_MUESTRA).notna(), '')
    return {
        'file': archivo, 'link': liga, 'rows': int(tabla.shape[0]), 'cols': int(tabla.shape[1]),
        'numeric': tipos.count('number'), 'text': tipos.count('text'), 'dates': tipos.count('date/time'),
        'empty_pct': round(100 * (1 - llenas / celdas), 1) if celdas else 0,
        'columns': columnas,
        'preview': [[str(v)[:40] for v in fila] for fila in muestra.values.tolist()],
    }


def main():
    procesados = {}
    for inv, relativa in ELEGIDOS.items():
        ruta = PREFINAL + inv + '/' + relativa
        if any(s in os.path.basename(ruta) for s in SALTAR):
            print(inv, '-> ese archivo no se debe abrir, se salta')
            continue
        if not os.path.isfile(ruta):
            print(inv, '-> NO existe', relativa)
            continue
        carpeta_salida = PREFINAL + inv + '/Procesado/'
        os.makedirs(carpeta_salida, exist_ok=True)
        tablas = []
        for nombre, tabla in tablas_de_archivo(ruta):
            tabla.to_csv(carpeta_salida + nombre + '.csv', index=False)
            liga = urllib.parse.quote(f'../{inv}/Procesado/{nombre}.csv', safe='/.')  # link desde dash/
            tablas.append(resume_tabla(nombre + '.csv', tabla, liga))
        procesados[inv] = {'source': os.path.basename(relativa), 'source_folder': os.path.dirname(relativa),
                           'folder': f'Prefinal/{inv}/Procesado', 'tables': tablas}
        print(f'{inv}: {os.path.basename(relativa)} -> {len(tablas)} csv', [(t['file'], t['rows'], t['cols']) for t in tablas])
    salida = os.path.join(AQUI, 'procesados.js')
    with open(salida, 'w', encoding='utf-8') as f:
        f.write('window.PROCESADOS = ' + json.dumps(procesados, ensure_ascii=False) + ';\n')
    print('Listo:', salida, round(os.path.getsize(salida) / 1024), 'KB')


if __name__ == '__main__':
    main()
