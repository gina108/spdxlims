"""Quick raw-send test for the YAEN D3 via the Windows spooler.

Tries TSPL first (most common for thermal label printers).
Run from the repo root:
    python niimbot-helper/scripts/_yaen_test_raw.py
"""
import sys
import win32print

PRINTER_NAME = "YAEN D3"

# TSPL test label — 50x30 mm, 3 mm gap
TSPL_TEST = "\r\n".join([
    "SIZE 50 mm, 30 mm",
    "GAP 3 mm, 0 mm",
    "CLS",
    'TEXT 25,10,"4",0,1,1,"TEST PRINT"',
    'TEXT 25,60,"3",0,1,1,"SPDXLIMS"',
    "PRINT 1,1",
    "",
]).encode("ascii")

# ESC/POS test (fallback)
ESCPOS_TEST = (
    b"\x1b@"               # ESC @ init
    b"TEST PRINT\n"
    b"SPDXLIMS\n"
    b"\n\n\n"
    b"\x1dV\x41\x03"       # GS V cut
)

def raw_print(printer_name: str, data: bytes) -> None:
    h = win32print.OpenPrinter(printer_name)
    try:
        job = win32print.StartDocPrinter(h, 1, ("YAEN D3 test", None, "RAW"))
        try:
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, data)
            win32print.EndPagePrinter(h)
        finally:
            win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def main() -> int:
    protocol = sys.argv[1].lower() if len(sys.argv) > 1 else "tspl"
    data = ESCPOS_TEST if protocol == "escpos" else TSPL_TEST
    print(f"Sending {protocol.upper()} test to '{PRINTER_NAME}'...")
    try:
        raw_print(PRINTER_NAME, data)
        print("Spooler accepted the job. Check the printer for output.")
        print("If nothing printed, re-run with: python _yaen_test_raw.py escpos")
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
