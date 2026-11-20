import glob
import io
import re
import pandas as pd
import os

CARPETA = 'C:/Users/noego/Desktop/SpaceApp/Prefinal/'
INVESTIGACIONES = ['PSI-25','PSI-26','PSI-68','PSI-69','PSI-98','PSI-99','PSI-100'] # las que usamos en el reto: 'PSI-25', 'PSI-26', 'PSI-68', 'PSI-69', 'PSI-98', 'PSI-99', 'PSI-100'
LIMITE = 256 * 1024
RAYA = re.compile(r'^[ \t]*=+([ \t]+=+)+[ \t]*\r?$', re.M)  # renglon de puras rayas '=====   =====' (\r: fin de linea de Windows)

def extract_csv(texto):
	lineas_a_revisar = 300  # para decidir solo se ven las primeras 300 lineas; los datos si se leen completos
	separadores = [',', ';', '\t', '|']  # si dos empatan, gana el primero de la lista

	#texto = texto.lstrip('\ufeff')  # la marca BOM del inicio no es parte del primer nombre
	 
	# 0. Tablas subrayadas con ===== (como los reportes A109D03.txt): el renglon de arriba de la raya son los
	#    encabezados y los de abajo los datos, hasta la primera linea vacia. Las columnas van alineadas
	#    (con tabs de 8 espacios), asi que cada raya ===== marca donde empieza cada columna.
	#    Si hay varias tablas subrayadas, se toma la que tiene mas filas de datos.
	todas_lineas = [l.expandtabs(8) for l in re.split(r'\r\n|\r|\n', texto)]
	mejor = None  # (linea de la raya, linea donde se acaban los datos)
	for n in range(1, min(len(todas_lineas), lineas_a_revisar)):
		raya = todas_lineas[n]
		if len(re.findall(r'=+|-+', raya)) >= 2 and re.sub(r'[=\- ]', '', raya) == '' and todas_lineas[n - 1].strip():
			fin = n + 1
			while fin < len(todas_lineas) and todas_lineas[fin].strip():
				fin += 1  # los datos siguen hasta la primera linea vacia
			if fin - n - 1 >= 2 and (mejor is None or fin - n > mejor[1] - mejor[0]):
				mejor = (n, fin)
	if mejor:
		n, fin = mejor
		inicios = [r.start() for r in re.finditer(r'=+|-+', todas_lineas[n])]
		if inicios[0] > 0:
			inicios = [0] + inicios  # a la izquierda hay una columna sin raya (por ejemplo IPSU1, IPSU2...)
		cortes = list(zip(inicios, inicios[1:] + [None]))  # cada columna va de su raya hasta la siguiente
		encabezados = [todas_lineas[n - 1][a:b].strip() for a, b in cortes]
		datos = pd.read_fwf(io.StringIO('\n'.join(todas_lineas[n + 1:fin])), colspecs=cortes, header=None,
			names=list(range(len(cortes))), keep_default_na=False, na_values=[''])
		datos.columns = encabezados
		return True, datos

	lineas = re.split(r'\r\n|\r|\n', texto[:LIMITE])
	if len(texto) > LIMITE:
		lineas = lineas[:-1]  # la ultima quedo cortada a la mitad
	lineas = pd.Series(lineas[:lineas_a_revisar])
	lineas = lineas[lineas.str.strip() != '']  # sin lineas vacias (el indice guarda el numero de linea original)
	if lineas.empty:
		return False, None

	# 1. Con cada separador se cuentan los campos de cada linea (lo que va entre comillas no se cuenta)
	#    y se buscan lineas seguidas con el mismo numero de campos (un bloque). El bloque mas largo es la tabla.
	#    Con coma o punto y coma se acepta una fila con un campo menos (la ultima columna vacia sin su coma)
	sin_comillas = lineas.str.replace(r'"[^"]*"', '""', regex=True)
	inicio_tabla, fin_tabla, sep, con_separador = 0, 0, None, 0
	for s in separadores:
		campos = (sin_comillas.str.count(re.escape(s)) + 1).tolist()
		inicio = 0
		for i in range(1, len(campos) + 1):
			ancho = campos[inicio]
			sigue = i < len(campos) and (campos[i] == ancho or (s in ',;' and campos[i] == ancho - 1 >= 2))
			if not sigue:  # aqui se acaba un bloque
				if ancho > 1 and i - inicio > fin_tabla - inicio_tabla:
					inicio_tabla, fin_tabla, sep = inicio, i, s
					con_separador = sum(c > 1 for c in campos)  # lineas con separador (una nota de texto no cuenta)
				inicio = i
	if sep is None:
		return False, None
	filas, todas = fin_tabla - inicio_tabla, len(lineas)

	# 2. Es CSV solo si la tabla es de verdad: larga (10 filas) o casi todo el texto (80 %).
	#    Un texto normal o lineas tipo 'Nombre:<tab>valor' no cumplen
	if filas == 2 and (inicio_tabla > 0 or con_separador > 2 or todas > 4):
		return False, None  # encabezado + 1 fila solo cuenta si es el texto completo (una nota corta al final si se vale)
	if 2 < filas < 10 and filas < todas * 0.8:
		return False, None
	if inicio_tabla > 0:
		raya = re.sub(r'[\s,;|]', '', lineas.iloc[inicio_tabla - 1])
		if set(raya) <= set('=-_'):
			return False, None  # arriba de los datos hay una raya '=====': es una tabla de ancho fijo (la saca columnas_txt_excel.py)

	# 3. Se lee el bloque como DataFrame (todo como texto, sin encabezados todavia)
	try:
		bloque = io.StringIO('\n'.join(lineas.iloc[inicio_tabla:fin_tabla]))
		tabla = pd.read_csv(bloque, sep=sep, header=None, dtype=str, keep_default_na=False, skipinitialspace=True)
	except Exception:
		return False, None  # pandas no la pudo leer como tabla
	tabla = tabla.fillna('').apply(lambda columna: columna.str.strip())
	llenas = (tabla != '').sum(axis=1)  # cuantas celdas con dato tiene cada fila

	if filas == 1:
		# el texto completo es una sola linea: solo cuenta si parece fila de encabezados (3 nombres cortos o mas)
		if todas != 1 or tabla.shape[1] < 3 or any(c == '' or len(c.split()) > 4 for c in tabla.iloc[0]):
			return False, None
	elif (llenas >= 2).sum() < len(tabla) / 2:
		return False, None  # casi todas las filas tienen un solo dato (por ejemplo texto con sangria): no es tabla

	# 4. Desde arriba, la primera fila de la tabla son los encabezados, si no son numeros
	encabezados, desde = None, inicio_tabla
	for i in range(len(tabla)):
		if i + 1 < len(tabla) and llenas.iloc[i] < llenas.iloc[i + 1]:
			continue  # tiene celdas vacias de relleno (un titulo) y la de abajo esta mas llena: no son encabezados
		celdas = [c for c in tabla.iloc[i] if c != '']
		if any(len(c) > 80 for c in celdas):
			return False, None  # un nombre de columna no mide un parrafo: es texto, no tabla
		# cuenta como numero todo lo que sea digitos y signos: 1.5, -3e5, 21.190%, 22:56:17, 2016-04-18 14:57:14
		numeros = sum(1 for c in celdas if any(ch.isdigit() for ch in c) and all(ch in '0123456789.,:;+-eE /%' for ch in c))
		if numeros <= len(celdas) / 2:
			encabezados = list(tabla.iloc[i])  # esa fila son los nombres de las columnas
		desde = inicio_tabla + i  # si son numeros, ahi mismo empiezan los datos (CSV sin encabezados)
		break

	# 5. Ya que se sabe donde empieza, se leen TODOS los datos del texto (no solo las primeras 300 lineas)
	numero_linea = lineas.index[desde]  # numero de linea en el texto original (contando las vacias)
	saltar = numero_linea + 1 if encabezados else numero_linea
	try:
		datos = pd.read_csv(io.StringIO(texto), sep=sep, header=None, skiprows=saltar, names=list(range(tabla.shape[1])),
			index_col=False, skipinitialspace=True, on_bad_lines='skip', keep_default_na=False, na_values=[''])
	except pd.errors.EmptyDataError:
		datos = pd.DataFrame(columns=list(range(tabla.shape[1])))  # solo trae encabezados, sin filas de datos
	# renglones con columnas de mas se saltan; los datos no se limpian ni se cambian (eso lo hace el equipo despues)
	if encabezados:
		datos.columns = encabezados
	return True, datos


def parece_encabezado(celdas):
	# Una fila de nombres de columna: sin celdas vacias, sin numeros, nombres cortos (5 palabras maximo, una frase
	# no es un nombre de columna) y sin ':' ni '=' (eso es 'clave: valor')
	numero = lambda c: any(ch.isdigit() for ch in c) and all(ch in '0123456789.,:;+-eE /%' for ch in c)
	return all(c != '' and not numero(c) and len(c) <= 80 and len(c.split()) <= 5 and ':' not in c and '=' not in c
		for c in celdas)


def es_tabla(texto):
	# Igual que es_csv, pero si es_csv dice False se prueban otros formatos de tabla que tambien vienen en los
	# .txt y .csv de data/raw. Lo que es_csv ya lee bien no cambia. Regresa (True, tabla) o (False, None),
	# y en tabla.attrs['formato'] dice como se leyo.
	separadores = [',', ';', '\t', '|']
	numero = lambda c: any(ch.isdigit() for ch in c) and all(ch in '0123456789.,:;+-eE /%' for ch in c)
	texto = texto.lstrip('﻿')

	# A. CSV con bytes nulos (algunos _data.csv de PSI-20, 21, 22, 23 y 159): unos bloques de bytes nulos borraron
	#    pedazos de algunas lineas. Se quitan solo esas lineas danadas; si lo que queda no es texto, es un binario
	formato = 'csv'
	if '\x00' in texto[:LIMITE]:
		texto = re.sub(r'[^\r\n]*\x00[^\r\n]*(\r\n|\r|\n)?', '', texto)
		muestra = texto[:LIMITE]
		raros = len(re.findall(r'[\x01-\x08\x0b\x0e-\x1f\x7f-\x9f]', muestra))
		if not muestra.strip() or raros > len(muestra) / 1000:
			return False, None  # es un binario (por ejemplo un PDF guardado como .txt)
		formato = 'csv (se quitaron lineas con bytes nulos)'

	csv_si, tabla = extract_csv(texto)
	if csv_si:
		tabla.attrs['formato'] = formato
		return True, tabla
	lineas = [l.strip() for l in re.split(r'\r\n|\r|\n', texto) if l.strip()]  # lineas con texto

	# B. Celdas entre comillas que ocupan varias lineas (como DAFT.csv de PSI-47): es_csv cuenta campos por
	#    linea y ahi se descuadra, pero pandas si las sabe leer
	if '"' in texto:
		for s in separadores:
			try:
				prueba = pd.read_csv(io.StringIO(texto), sep=s, header=None, dtype=str, keep_default_na=False)
			except Exception:
				continue
			encabezado = [str(c).strip() for c in prueba.iloc[0]] if len(prueba) else []
			if (len(prueba) >= 3 and prueba.shape[1] >= 2 and not prueba.isna().any().any()
					and prueba.apply(lambda col: col.str.contains('\n')).any().any() and parece_encabezado(encabezado)):
				datos = pd.read_csv(io.StringIO(texto), sep=s, header=0, keep_default_na=False, na_values=[''])
				datos.columns = encabezado
				datos.attrs['formato'] = 'csv con celdas de varias lineas'
				return True, datos

	# C. Encabezado + filas que traen un valor de mas (como los X129R01/X140R01_Mixture.txt): el ultimo valor
	#    no tiene nombre de columna. Los valores se alinean desde la izquierda
	if '"' not in texto and len(lineas) >= 2:
		for s in separadores:
			encabezado = [c.strip() for c in lineas[0].split(s)]
			filas = [l.split(s) for l in lineas[1:]]
			n = len(encabezado)
			celdas = [c.strip() for f in filas for c in f]
			if (n >= 3 and parece_encabezado(encabezado) and all(len(f) == n + 1 for f in filas)
					and sum(numero(c) for c in celdas) >= 0.8 * len(celdas)):
				datos = pd.read_csv(io.StringIO('\n'.join(lineas[1:])), sep=s, header=None, names=list(range(n + 1)),
					index_col=False, keep_default_na=False, na_values=[''])
				datos.columns = encabezado + [f'Unnamed: {n}']
				datos.attrs['formato'] = 'csv con un valor de mas por fila'
				return True, datos

	k = 0
	while k < len(lineas) and re.fullmatch(r'[A-Za-z][^:]{0,40}:\s*.*', lineas[k]):
		k += 1
	resto = lineas[k:]
	if k >= 2 and len(resto) >= 10 and all(re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', l) for l in resto):
		metadatos = dict(re.match(r'([^:]+):\s*(.*)', l).groups() for l in lineas[:k])
		datos = pd.read_csv(io.StringIO('\n'.join(resto)), header=None, names=[metadatos.get('Units') or 'valor'])
		datos.attrs['metadatos'] = metadatos
		datos.attrs['formato'] = 'columna de numeros con datos clave: valor arriba'
		return True, datos

	# E. Solo dos lineas: una de datos generales ('Experiment: 1,Test Point: ...') y abajo los encabezados,
	#    sin filas de datos (como los _mfcSetpoints.csv y algunos _data.csv vacios de PSI-21)
	if len(lineas) == 2 and '"' not in texto:
		for s in separadores:
			arriba = [c.strip() for c in lineas[0].split(s)]
			encabezado = [c.strip() for c in lineas[1].split(s)]
			if len(encabezado) >= 3 and parece_encabezado(encabezado) and any(re.fullmatch(r'[A-Za-z][^:]{0,40}:\s*\S.*', c) for c in arriba):
				datos = pd.DataFrame(columns=encabezado)
				datos.attrs['formato'] = 'solo encabezados (abajo de una linea de datos generales)'
				return True, datos
	return False, None

def separar(texto):
	# Reportes como A109D03.txt: arriba datos 'clave: valor', en medio una tabla chica y abajo la tabla grande
	# (las dos subrayadas con =====). Se parte el texto en las lineas vacias y cada pedazo se lee aparte,
	# asi no importa en que linea empieza cada parte (cambia de un archivo a otro).
	# Regresa una lista de tablas en el orden del archivo. Las notas ('Note: ...') no son tabla y se saltan.
	partes = []
	texto = texto.replace('\r\n', '\n').replace('\r', '\n')
	for pedazo in re.split(r'\n[ \t]*\n', texto):
		lineas = [l.strip() for l in pedazo.split('\n') if l.strip()]
		if not lineas:
			continue
		if RAYA.search(pedazo):
			si, tabla = extract_csv(pedazo)  # tabla subrayada con ===== (la chica o la grande)
			if si:
				partes.append(tabla)
		elif len(lineas) >= 2 and all(re.match(r'[^:\t]+:', l) for l in lineas):
			# parte de arriba 'clave: valor': una sola fila, cada clave es una columna
			claves = [l.split(':', 1)[0].strip() for l in lineas]
			valores = [l.split(':', 1)[1].strip() for l in lineas]
			partes.append(pd.DataFrame([valores], columns=claves))
	return partes


def exportar(carpeta, investigaciones):
	# Lee los .txt y .csv de cada investigacion y guarda cada tabla como csv en carpeta/<investigacion>/Procesado/.
	# Los reportes con tablas ===== se parten con separar() y sus partes se numeran: A109D03_1.csv, _2, _3.
	guardados, falsos = 0, []
	for inv in investigaciones:
		ruta_salida = carpeta + inv + '/Procesado/'
		os.makedirs(ruta_salida, exist_ok=True)  # crea la carpeta si no existe
		usados = {}
		for ruta in glob.glob(carpeta + inv + '/**/*', recursive=True):
			if not ruta.lower().endswith(('.txt', '.csv')) or not os.path.isfile(ruta):
				continue
			if os.path.abspath(ruta).startswith(os.path.abspath(ruta_salida)):
				continue  # no se vuelven a leer los csv que ya se exportaron
			texto = open(ruta, 'rb').read().decode('utf-8-sig', errors='replace')
			if RAYA.search(texto[:LIMITE]):
				tablas = separar(texto)
			else:
				si, tabla = es_tabla(texto)
				tablas = [tabla] if si else []
			if not tablas:
				falsos.append(os.path.relpath(ruta, carpeta))
				continue
			base = os.path.splitext(os.path.basename(ruta))[0]  # 'A109D03'
			usados[base] = usados.get(base, 0) + 1
			if usados[base] > 1:
				base += f'_{usados[base]}'  # otro archivo con el mismo nombre en otra subcarpeta
			for i, tabla in enumerate(tablas, start=1):
				nombre = f'{base}_{i}' if len(tablas) > 1 else base  # partes del mismo archivo: _1, _2, _3
				tabla.to_csv(ruta_salida + nombre + '.csv', index=False)
				guardados += 1
		print(inv, '-> guardados en', ruta_salida)
	print('CSV guardados:', guardados)
	print('Archivos False (no son tabla):', len(falsos))
	for f in falsos:
		print('  False ->', f)


if __name__ == '__main__':  # corre solo si ejecutas este archivo, no cuando lo importas desde otro
	exportar(CARPETA, INVESTIGACIONES)
