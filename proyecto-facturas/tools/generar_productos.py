"""Lee datos/inventario_productos.csv y genera db/04_products.sql
(catálogo real de productos de AUTOREPUESTOS CARMAX, FR-06).

Uso (desde la carpeta del proyecto):   python tools/generar_productos.py

- La categoría se asigna por la primera palabra del nombre (FILTRO -> Filtros, ...).
  Lo que no coincide con ninguna regla va a "Otros repuestos".
- La unidad de medida se toma del nombre (GALON, LITRO, CANECA, KIT/JUEGO) o es "unidad".
- product_name es UNIQUE: si dos productos tienen el mismo nombre se les agrega
  el código entre corchetes para distinguirlos.
"""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "datos" / "inventario_productos.csv"
SALIDA = ROOT / "db" / "04_products.sql"

# La categoría 1 ("Repuestos automotrices") ya la crea 03_seed.sql
CATEGORIAS = {
    "Filtros": "FILTRO PREFILTRO",
    "Frenos y embrague": "PASTILLA PASTILLAS DISCO ZAPATA ZAPATAS TAMBOR CILINDRO EMBRAGUE BOMBIN",
    "Suspensión y dirección": "AMORTIGUADOR BASE TERMINAL BARRA MESA AXIAL ROTULA BUJE BRAZO CAUCHO "
                              "PITMAN BOCIN SUSPENSION BIELATA",
    "Bandas y distribución": "BANDA B. B.MOTOR B.TEMPL. TEMPLADOR TENSOR POLEA",
    "Kits y juegos": "KIT KITS JUEGO JGO. JGO SET",
    "Bombas": "BOMBA",
    "Sistema eléctrico y sensores": "SENSOR BOBINA BUJIA BUJIAS CABLE CABLES ALTERNADOR BATERIA FOCO FARO "
                                    "NEBLINERO CONECTOR CONCETOR TROMPO INYECTOR SWITCH PILA FUSIBLES "
                                    "FLASHER BOTON ELEVAVIDRIO REGULADOR",
    "Rodamientos y ejes": "RULIMAN RODAMIENTO MANZANA HOMOCINETICA HOMOCENTICA GUARDAPOLVO CRUCETA PINON "
                          "PLATO EJE PUNTA CUBO",
    "Empaques y retenes": "EMPAQUE EMPAQUES EMPAQ EMP. RETEN RETENEDOR SELLOS ANILLO",
    "Refrigeración": "RADIADORES RADIADOR TERMOSTATO RESERVORIO REFRIGERANTE MANGUERA MANGERA TOMA "
                     "ANTIFREEZE ZEREX ELECTROVENTILADOR ENFRIADOR ASPA RECIPIENTE DEPOSITO",
    "Lubricantes y químicos": "ACEITE ADITIVO AGUA LIQUIDO GRASA SILICONA SILICON SELLADOR EPOXICO AEROSOL "
                              "PEGAMENTO CERA SHAMPOO",
    "Motor": "VALVULA CARTER BALANCIN CUERPO CHAQUETA CHAQUETAS MOTOR",
    "Carrocería y accesorios": "LIMPIADOR PLUMA GUARDACHOCHE MASCARILLA TAPA TAPON AMBIENTAL AMBIENTALES "
                               "AMBIENTADOR AROMATIZANTE CINTA ABRAZADERA MANILLA EMBLEMA ESPEJO MOQUETA "
                               "CERRADURA BAYONETA GUIA",
    "Otros repuestos": "",
}
PALABRA_A_CATEGORIA = {p: cat for cat, palabras in CATEGORIAS.items() for p in palabras.split()}
ID_CATEGORIA = {cat: n for n, cat in enumerate(CATEGORIAS, 2)}


def categoria(nombre):
    primera = nombre.split()[0].upper()
    if primera.startswith("EMP/"):
        return "Empaques y retenes"
    return PALABRA_A_CATEGORIA.get(primera, "Otros repuestos")


def unidad(nombre, cat):
    palabras = nombre.upper().replace("(", " ").replace(")", " ").split()
    if "GALON" in palabras:
        return "galón"
    if "LITRO" in palabras:
        return "litro"
    if "CANECA" in palabras:
        return "caneca"
    if cat == "Kits y juegos":
        return "juego"
    return "unidad"


def q(texto):
    return "'" + texto.replace("\\", "\\\\").replace("'", "''") + "'"


def main():
    with open(CSV, encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    repetidos = {n for n, c in Counter(f["producto"] for f in filas).items() if c > 1}
    productos, por_categoria = [], Counter()
    for f in filas:
        nombre = " ".join(f["producto"].split())
        cat = categoria(nombre)
        uni = unidad(nombre, cat)
        if f["producto"] in repetidos:
            nombre = f"{nombre} [{f['codigo']}]"
        if len(nombre) > 150:
            raise SystemExit("Nombre demasiado largo: " + nombre)
        productos.append((nombre, ID_CATEGORIA[cat], uni))
        por_categoria[cat] += 1
    if len({p[0] for p in productos}) != len(productos):
        raise SystemExit("Quedaron nombres repetidos")

    out = [
        "-- =====================================================================",
        "--  04_products.sql  ->  Catálogo real de productos (AUTOREPUESTOS CARMAX)",
        "--  ARCHIVO GENERADO por tools/generar_productos.py a partir de",
        "--  datos/inventario_productos.csv (reporte 'Inventario de Productos').",
        "--  No editar a mano.",
        "-- =====================================================================",
        "",
        "SET NAMES utf8mb4;      -- para que las tildes se guarden bien",
        "",
        "INSERT INTO category (category_id, category_name) VALUES",
        ",\n".join(f"    ({n}, {q(cat)})" for cat, n in ID_CATEGORIA.items()) + ";",
    ]
    for i in range(0, len(productos), 500):
        bloque = productos[i:i + 500]
        out += [
            "",
            "INSERT INTO product (product_name, category_id, unit_of_measure) VALUES",
            ",\n".join(f"    ({q(n)}, {c}, {q(u)})" for n, c, u in bloque) + ";",
        ]
    SALIDA.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(productos)} productos en {len(ID_CATEGORIA)} categorías -> {SALIDA}")
    for cat, n in por_categoria.most_common():
        print(f"   {n:5d}  {cat}")


if __name__ == "__main__":
    main()
