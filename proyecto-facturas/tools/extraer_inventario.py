"""Lee el reporte "Inventario de Productos" (PDF de Crystal Reports) y genera
datos/inventario_productos.csv con: codigo, producto, cantidad, ultima_compra, ultimo_costo.

Uso (desde la carpeta del proyecto):   python tools/extraer_inventario.py
Necesita:  pip install pymupdf   y el programa pdftotext (Poppler).

No hace falta volver a ejecutarlo: el CSV ya está generado. Solo sirve si
llega un PDF de inventario más nuevo.

Cómo funciona: en el PDF los nombres largos salen recortados por el ancho de
la columna, así que se leen dos veces:
  1. por posición (PyMuPDF): código, cantidad, fecha y costo de cada fila;
  2. en orden de lectura (pdftotext -raw): el nombre completo.
"""
import csv
import re
import subprocess
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "datos" / "Inventario_Productos_CARMAX.pdf"
SALIDA = ROOT / "datos" / "inventario_productos.csv"

FECHA = re.compile(r"\d{2}-[a-z]+-\d{4}")
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
         "ago": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
ENCABEZADOS = re.compile(
    r"^(Dir:|RUC:|Telfs:|email:|web:|AUTOREPUESTOS CARMAX$|Inventario de Productos$|©3ap|"
    r"Código: Producto:|\d{2}-[a-z]+-\d{4} Página|Página \d+ de|Totales:)")


def filas_por_posicion(doc):
    """Devuelve una lista de filas con el código y los tres últimos datos."""
    filas = []
    for pagina in doc:
        palabras = sorted(pagina.get_text("words"), key=lambda w: (w[1], w[0]))
        lineas, actual, y = [], [], None
        for w in palabras:
            if y is None or abs(w[1] - y) > 2:
                if actual:
                    lineas.append(actual)
                actual, y = [w], w[1]
            else:
                actual.append(w)
        if actual:
            lineas.append(actual)
        for linea in lineas:
            linea.sort(key=lambda w: w[0])
            textos = [w[4] for w in linea]
            pos = [i for i, t in enumerate(textos) if FECHA.fullmatch(t)]
            if not pos or pos[-1] < 2 or pos[-1] + 1 >= len(textos):
                continue
            i = pos[-1]
            codigo = " ".join(w[4] for w in linea[:i - 1] if w[0] < 100)
            recortado = " ".join(w[4] for w in linea[:i - 1] if w[0] >= 100)
            if codigo:
                filas.append({"codigo": codigo, "recortado": recortado, "cantidad": textos[i - 1],
                              "fecha": textos[i], "costo": textos[i + 1]})
    return filas


def main():
    filas = filas_por_posicion(pymupdf.open(PDF))
    crudo = subprocess.run(["pdftotext", "-raw", str(PDF), "-"],
                           capture_output=True, text=True, check=True).stdout
    texto = " ".join(ln.strip() for ln in crudo.replace("\f", "\n").splitlines()
                     if ln.strip() and not ENCABEZADOS.match(ln.strip()))
    texto = re.sub(r"\s+", " ", texto)

    productos, pos = [], 0
    for f in filas:
        final = f"{f['cantidad']} {f['fecha']} {f['costo']}"
        inicio = texto.find(f["codigo"], pos)
        fin = texto.find(final, inicio)
        if inicio < 0 or fin < 0 or texto[pos:inicio].strip():
            raise SystemExit(f"No se pudo ubicar la fila {f}")
        codigo = f["codigo"]
        nombre = texto[inicio + len(codigo):fin].strip()
        primera = f["recortado"].split(" ")[0] if f["recortado"] else ""
        if primera and not nombre.startswith(primera) and primera in nombre:
            corte = nombre.find(primera)             # el código era más ancho que su columna
            codigo = (codigo + nombre[:corte]).strip()
            nombre = nombre[corte:].strip()
        dia, mes, anio = f["fecha"].split("-")
        productos.append([codigo, nombre, f["cantidad"].replace(",", ""),
                          f"{anio}-{MESES[mes]:02d}-{dia}", f["costo"].replace(",", "")])
        pos = fin + len(final)
        while pos < len(texto) and texto[pos] == " ":
            pos += 1
    if texto[pos:].strip():
        raise SystemExit("Quedó texto sin leer: " + texto[pos:pos + 80])

    with open(SALIDA, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["codigo", "producto", "cantidad", "ultima_compra", "ultimo_costo"])
        w.writerows(productos)
    total = sum(float(p[2]) for p in productos)
    print(f"{len(productos)} productos, cantidad total {total:,.2f} -> {SALIDA}")


if __name__ == "__main__":
    main()
