"""Die Oberfläche: erreichbar, und die Bildroute lässt sich nicht austricksen.

Bewusst ohne echte PDFs - es geht um Routing und Absicherung, nicht um OCR.
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="UI-Extra nicht installiert")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


class TestSeitenErreichbar:
    @pytest.mark.parametrize("url", ["/", "/system", "/laeufe"])
    def test_get(self, url):
        r = client.get(url)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_deutsche_oberflaeche(self):
        assert "Fall öffnen" in client.get("/").text

    def test_unbekannter_lauf_gibt_404(self):
        r = client.get("/laeufe/2026-01-01T00-00-00_gibtsnicht")
        assert r.status_code == 404


class TestOrdnerAuswahl:
    def test_nicht_existierender_pfad_gibt_422_statt_traceback(self, tmp_path):
        r = client.post("/oeffnen", data={"pfad": str(tmp_path / "gibtsnicht")},
                        follow_redirects=False)
        assert r.status_code == 422
        assert "Kein Verzeichnis" in r.text

    def test_eingegebener_wert_bleibt_stehen(self, tmp_path):
        pfad = str(tmp_path / "tippfehler")
        assert pfad in client.post("/oeffnen", data={"pfad": pfad},
                                   follow_redirects=False).text

    def test_gueltiger_ordner_leitet_weiter(self, tmp_path):
        r = client.post("/oeffnen", data={"pfad": str(tmp_path)}, follow_redirects=False)
        assert r.status_code == 303
        assert "/fall?pfad=" in r.headers["location"]


class TestBildroute:
    """Die Route liest aus dem Zwischenspeicher, der Seiten aus Patientenakten
    enthält. Digest und Seitenzahl kommen aus der URL - beide müssen geprüft
    werden, sonst ist die Route ein Leseweg auf das Dateisystem."""

    @pytest.mark.parametrize("digest", [
        "../../etc", "..", "/etc/passwd", "a/b", "", "ZZZZZZZZZZZZ",
        "0123456789ab0", "0123456789a", "..%2f..%2fetc",
    ])
    def test_ungueltige_digests_werden_abgewiesen(self, digest):
        assert client.get(f"/bild/{digest}/1").status_code == 404

    @pytest.mark.parametrize("page", [0, -1, 99999])
    def test_seitenzahlen_ausserhalb_des_bereichs(self, page):
        assert client.get(f"/bild/0123456789ab/{page}").status_code == 404

    def test_gueltige_form_aber_unbekanntes_dokument(self):
        assert client.get("/bild/0123456789ab/1").status_code == 404


class TestPruefen:
    def test_unbekanntes_pdf(self, tmp_path):
        r = client.get("/pruefen", params={"pdf": str(tmp_path / "gibtsnicht.pdf")})
        assert r.status_code == 404

    def test_nicht_analysiertes_pdf_sagt_das(self, tmp_path):
        pdf = tmp_path / "leer.pdf"
        import fitz
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf)
        doc.close()
        r = client.get("/pruefen", params={"pdf": str(pdf)})
        assert r.status_code == 404
        assert "analysiert" in r.json()["detail"]
