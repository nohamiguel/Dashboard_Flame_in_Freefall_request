import os
import re
import csv
import json
import collections
import urllib.parse
from pathlib import Path

# Junta todo lo que muestra el dashboard completo en un solo archivo: datos.js
# Uso: py construir_datos.py              -> escribe dashboard/datos.js (junto al index.html del dashboard)
#      py construir_datos.py <carpeta>    -> escribe <carpeta>/datos.js (los links quedan relativos a esa carpeta)
# Correrlo otra vez cada que cambien las tablas, las imagenes, contenido.json o hallazgos.json

import sys

AQUI = Path(__file__).resolve().parent  # Pruebas/dashboard_completo (contenido.json, hallazgos.json, imagenes.json)
RAIZ = AQUI.parent.parent  # carpeta SpaceApp
DASH = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else RAIZ / 'dashboard'  # donde queda datos.js
IMAGENES = RAIZ / 'dashboard' / 'img'
INVESTIGACIONES = ['PSI-69', 'PSI-25', 'PSI-26', 'PSI-68', 'PSI-98', 'PSI-99', 'PSI-100']  # las 7 del reto, en el orden del dashboard

# Carpetas de donde salen las tablas de la seccion "Data explorer". Para agregar tablas basta con poner un CSV en alguna
CARPETAS_TABLAS = [(RAIZ / 'data' / 'raw' / i / 'Experimental table', 'NASA PSI experimental table') for i in INVESTIGACIONES]
CARPETAS_TABLAS.append((RAIZ / 'Pruebas' / 'limpios', 'Team cleaned data'))

FICHAS = RAIZ / 'data' / 'recursos_reto' / 'psi' / 'fichas'
INDICE = RAIZ / 'data' / 'raw' / 'indice_descargas.csv'
VOCABULARIO = [RAIZ / 'Pruebas' / 'columnas_csv.txt', RAIZ / 'Pruebas' / 'columnas_txt_excel.txt']
DOCUMENTOS = RAIZ / 'data' / 'recursos_reto' / 'documentos'
MAX_FILAS = 20000  # filas maximas por tabla dentro de datos.js
SEPARADORES = [',', ';', '\t', '|']

# Hojas informativas de la NASA (ya descargadas) que van con cada experimento
DOCS_NASA = {
	'PSI-69': ['flame-extinguishment-experiment-flex.pdf'],
	'PSI-68': ['flame-extinguishment-experiment-flex.pdf'],
	'PSI-25': ['burning-and-suppression-of-solids-bass.pdf', 'BASS_NTRS/*.pdf'],
	'PSI-26': ['burning-and-suppression-of-solids-bass.pdf', 'BASS_NTRS/*.pdf'],
	'PSI-98': ['spacecraft-fire-safety-demonstration-saffire.pdf'],
	'PSI-99': ['spacecraft-fire-safety-demonstration-saffire.pdf'],
	'PSI-100': ['spacecraft-fire-safety-demonstration-saffire.pdf'],
}
MINI_LIBRO = 'np-2015-10-034-jsc_combustion_in_reduced_gravity-iss-mini-book-011116-508.pdf'


def ruta_web(ruta):
	# Ruta relativa desde dashboard/ para usarla como link en el HTML (con espacios codificados)
	relativa = os.path.relpath(ruta, DASH).replace('\\', '/')
	return urllib.parse.quote(relativa, safe='/')


def leer_texto(ruta):
	for codificacion in ['utf-8-sig', 'latin-1']:  # FLEX viene en latin-1
		try:
			return Path(ruta).read_text(encoding=codificacion), codificacion
		except UnicodeDecodeError:
			pass


def llenos(fila):
	return [c.strip() for c in fila if c.strip()]


def elegir_separador(lineas):
	# El separador correcto es el que hace que mas lineas tengan el mismo numero de campos
	mejor, puntos = ',', 0
	for sep in SEPARADORES:
		conteo = collections.Counter(len(f) for f in csv.reader(lineas, delimiter=sep) if llenos(f))
		if conteo:
			ancho, veces = conteo.most_common(1)[0]
			if ancho > 1 and veces > puntos:
				mejor, puntos = sep, veces
	return mejor


def es_metadatos(fila):
	celdas = llenos(fila)
	pistas = sum(': ' in c or c.endswith(':') for c in celdas)
	return len(celdas) > 0 and pistas >= len(celdas) / 2


def buscar_encabezado(filas):
	# Igual que columnas_csv.py: la primera fila con el ancho de la tabla que no sean numeros ni metadatos
	anchos = [len(f) for f in filas if llenos(f) and not es_metadatos(f)]
	if not anchos:
		return 0
	ancho = collections.Counter(anchos).most_common(1)[0][0]
	for i, fila in enumerate(filas):
		if len(fila) == ancho and llenos(fila) and not es_metadatos(fila):
			return i
	return 0


def leer_tabla(ruta):
	texto, codificacion = leer_texto(ruta)
	lineas = texto.splitlines()
	sep = elegir_separador(lineas[:60])
	filas = list(csv.reader(lineas, delimiter=sep))
	if filas and len(filas[0]) == 1 and sep in filas[0][0]:
		# Cada linea viene entera entre comillas (asi quedo el CSV limpio del equipo): se quitan para poder leerla
		lineas = [l[1:-1].replace('""', '"') if l.startswith('"') and l.endswith('"') else l for l in lineas]
		filas = list(csv.reader(lineas, delimiter=sep))
	inicio = buscar_encabezado(filas[:60])
	columnas = [c.strip() for c in filas[inicio]]
	datos = [f for f in filas[inicio + 1:] if llenos(f)]
	datos = [(f + [''] * len(columnas))[:len(columnas)] for f in datos]  # todas las filas con el mismo ancho
	return columnas, datos, codificacion


def leer_fichas():
	fichas = {}
	for inv in INVESTIGACIONES:
		d = json.loads((FICHAS / f'{inv}.json').read_text(encoding='utf-8'))
		contactos = [' '.join(x for x in [c.get('firstName'), c.get('lastName')] if x) for c in d.get('contacts') or [] if isinstance(c, dict)]
		publicaciones = []
		for p in d.get('publications') or []:
			if isinstance(p, dict) and p.get('title'):
				doi = (p.get('doi') or '').strip()
				publicaciones.append({'title': re.sub(r'\s+', ' ', p['title']).strip(), 'url': f'https://doi.org/{doi}' if doi else ''})
		fichas[inv] = {
			'title': d.get('title', ''),
			'hardware': d.get('experimentHardware', ''),
			'start': d.get('investigationStartDate', ''),
			'end': d.get('investigationEndDate', ''),
			'doi': d.get('doi', ''),
			'license': d.get('licenseName', ''),
			'area': d.get('subResearchArea', ''),
			'center': d.get('managingNasaCenter', ''),
			'people': contactos,  # solo nombres, sin correos
			'publications': publicaciones,
		}
	return fichas


def leer_recursos():
	# Documentos de cada investigacion segun el indice de descargas (solo los que si estan en la compu)
	recursos = collections.defaultdict(list)
	crudos = collections.Counter()
	with open(INDICE, encoding='utf-8-sig') as f:
		for fila in csv.DictReader(f):
			inv = fila['id']
			if inv not in INVESTIGACIONES or not os.path.exists(fila['ruta_local']):
				continue
			if fila['categoria'] in ('Raw Data', 'Calibration'):
				crudos[inv] += 1  # los datos crudos son miles: solo se cuentan
				continue
			nombre = re.sub(r'^PSI-\d+_' + re.escape(fila['categoria']) + r'_', '', fila['nombre'])
			recursos[inv].append({'name': nombre, 'category': fila['categoria'], 'ext': fila['extension'].lower().strip('.'),
				'mb': float(fila['mb'] or 0), 'link': ruta_web(fila['ruta_local'])})
	return recursos, crudos


def contar_archivos(inv):
	# Todo lo que hay en la compu de esa investigacion (incluye lo que sacamos de los ZIP)
	n, total = 0, 0
	for carpeta, _, archivos in os.walk(RAIZ / 'data' / 'raw' / inv):
		for a in archivos:
			n += 1
			total += os.path.getsize(os.path.join(carpeta, a))
	return n, total


def docs_nasa(inv):
	lista = []
	for patron in DOCS_NASA.get(inv, []) + [MINI_LIBRO]:
		for ruta in sorted(DOCUMENTOS.glob(patron)):
			lista.append({'name': ruta.name, 'category': 'NASA overview' if ruta.parent == DOCUMENTOS else 'NASA technical report (NTRS)',
				'ext': ruta.suffix.lower().strip('.'), 'mb': round(ruta.stat().st_size / 1e6, 2), 'link': ruta_web(ruta)})
	return lista


def periodo(exp, ficha, tablas_por_archivo):
	if exp.get('period_source') == 'manual':
		return exp.get('period', '')
	if exp.get('period_source') == 'table' and exp.get('table') in tablas_por_archivo:
		t = tablas_por_archivo[exp['table']]
		anios = set()
		for i, c in enumerate(t['columns']):
			if 'date' in c.lower():
				for fila in t['rows']:
					anios.update(int(a) for a in re.findall(r'\b(20[0-2]\d)\b', fila[i]))
		if anios:
			return str(min(anios)) if min(anios) == max(anios) else f'{min(anios)}–{max(anios)}'
	anios = [m for m in (re.search(r'(\d{4})$', ficha.get('start', '')), re.search(r'(\d{4})$', ficha.get('end', ''))) if m]
	anios = [a.group(1) for a in anios]
	return '–'.join(dict.fromkeys(anios))


def main():
	contenido = json.loads((AQUI / 'contenido.json').read_text(encoding='utf-8'))
	fichas = leer_fichas()
	recursos, crudos = leer_recursos()

	tablas = []
	for carpeta, origen in CARPETAS_TABLAS:
		for ruta in sorted(carpeta.glob('*.csv')):
			columnas, filas, codificacion = leer_tabla(ruta)
			inv = re.match(r'(PSI-\d+)', ruta.name)
			tablas.append({'id': f't{len(tablas)}', 'file': ruta.name, 'investigation': inv.group(1) if inv else '',
				'source': origen, 'folder': os.path.relpath(carpeta, RAIZ).replace('\\', '/'), 'link': ruta_web(ruta),
				'encoding': codificacion, 'n_rows': len(filas), 'columns': columnas, 'rows': filas[:MAX_FILAS]})
	por_archivo = {t['file']: t for t in tablas}

	hallazgos = json.loads((AQUI / 'hallazgos.json').read_text(encoding='utf-8'))  # hallazgos con fuente (documento y pagina)
	creditos = json.loads((AQUI / 'imagenes.json').read_text(encoding='utf-8'))  # de donde salio cada foto

	experimentos = []
	for exp in contenido['experimentos']:
		inv = exp['id']
		ficha = fichas[inv]
		n_archivos, bytes_locales = contar_archivos(inv)
		imagen = IMAGENES / f'{inv}.jpg'
		credito = creditos.get(inv, {})
		# Galeria: lista "gallery" de imagenes.json; si no existe, se usa la foto unica (formato anterior)
		galeria = []
		for foto in credito.get('gallery') or ([credito] if credito.get('file') else []):
			ruta_foto = RAIZ / 'dashboard' / foto['file']
			if ruta_foto.exists():
				galeria.append({'image': ruta_web(ruta_foto), 'caption': foto.get('caption', ''), 'source': foto.get('source', ''), 'page': foto.get('page')})
		exp = dict(exp)
		exp.update({
			'ficha': ficha,
			'period': periodo(exp, ficha, por_archivo),
			'image': ruta_web(imagen) if imagen.exists() else '',
			'gallery': galeria,
			'image_caption': credito.get('caption', ''),
			'image_source': credito.get('source', ''),
			'findings': hallazgos.get(inv, {}).get('findings', []),
			'safety_insight': hallazgos.get(inv, {}).get('safety_insight', ''),
			'resources': recursos.get(inv, []) + docs_nasa(inv),
			'raw_files': crudos.get(inv, 0),
			'local_files': n_archivos,
			'local_gb': round(bytes_locales / 1e9, 2),
			'raw_link': ruta_web(RAIZ / 'data' / 'raw' / inv / 'Raw Data') if (RAIZ / 'data' / 'raw' / inv / 'Raw Data').exists() else '',
			'tables': [t['id'] for t in tablas if t['investigation'] == inv],
		})
		experimentos.append(exp)

	vocabulario = []
	for archivo in VOCABULARIO:
		if archivo.exists():
			vocabulario += [n.strip() for n in archivo.read_text(encoding='utf-8').split(', ') if n.strip()]
	vocabulario = list(dict.fromkeys(vocabulario))

	resumen = {
		'investigations': len(experimentos),
		'tests': sum(e.get('tests', 0) for e in experimentos),
		'local_files': sum(e['local_files'] for e in experimentos),
		'local_gb': round(sum(e['local_gb'] for e in experimentos), 1),
		'documents': sum(len(e['resources']) for e in experimentos),
		'tables': len(tablas),
		'variables_documented': sum(len(e['variables']) for e in experimentos),
		'column_names': len(vocabulario),
	}
	datos = {'summary': resumen, 'experiments': experimentos, 'tables': tablas, 'vocabulary': vocabulario}
	salida = DASH / 'datos.js'
	salida.write_text('window.DASH = ' + json.dumps(datos, ensure_ascii=False) + ';\n', encoding='utf-8')
	print('Listo:', salida, round(salida.stat().st_size / 1e6, 2), 'MB')
	print(resumen)
	for e in experimentos:
		print(f"  {e['id']:8} {e['acronym']:12} periodo={e['period']:10} imagen={'si' if e['image'] else 'NO':3} recursos={len(e['resources']):3} tablas={len(e['tables'])} archivos={e['local_files']}")


if __name__ == '__main__':
	main()
