"""Testy skryptu budującego rozkład. Uruchomienie: python3 -m unittest"""
import datetime as dt
import io
import json
import os
import tempfile
import unittest
import zipfile

import zbuduj_rozklad as zb

FIKSTURA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fikstury', 'mini_gtfs')


def zip_fikstury():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for f in os.listdir(FIKSTURA):
            z.write(os.path.join(FIKSTURA, f), f)
    return buf.getvalue()


def kierunek(r, linia, kier):
    return next(d for d in r['dirs'] if d['line'] == linia and d['dir'] == kier)


def nazwy(r, d):
    return [r['stops'][i]['n'] for i in d['stops']]


class WyborPliku(unittest.TestCase):
    HTML = ('<td>OtwartyWroclaw_rozklad_jazdy_GTFS_16112026</td><a href="/hdb/download/162/">'
            '<td>OtwartyWroclaw_rozklad_jazdy_GTFS_07112026</td><a href="/hdb/download/160/">'
            '<td>OtwartyWroclaw_rozklad_jazdy_GTFS_03112026</td><a href="/hdb/download/156/">')

    def test_lista(self):
        self.assertEqual(zb.lista_plikow(self.HTML)[0], (dt.date(2026, 11, 16), '162'))
        self.assertEqual(len(zb.lista_plikow(self.HTML)), 3)

    def test_nie_bierze_pliku_z_przyszlosci(self):  # AC15
        pliki = zb.lista_plikow(self.HTML)
        self.assertEqual(zb.wybierz_plik(pliki, dt.date(2026, 11, 14))[1], '160')
        self.assertEqual(zb.wybierz_plik(pliki, dt.date(2026, 11, 16))[1], '162')

    def test_brak_pliku(self):
        with self.assertRaises(ValueError):
            zb.wybierz_plik(zb.lista_plikow(self.HTML), dt.date(2026, 1, 1))


class Budowa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = zb.zbuduj(zipfile.ZipFile(io.BytesIO(zip_fikstury())))

    def test_tylko_linie_3_i_5(self):
        self.assertEqual(sorted({d['line'] for d in self.r['dirs']}), ['3', '5'])
        self.assertEqual(len(self.r['dirs']), 4)

    def test_kolejnosc_przystankow_bez_petli(self):  # AC3
        self.assertEqual(nazwy(self.r, kierunek(self.r, '3', 0)), ['Alfa', 'Beta', 'Cent'])
        self.assertEqual(nazwy(self.r, kierunek(self.r, '3', 1)), ['Delta', 'Cent', 'Beta'])
        self.assertEqual(kierunek(self.r, '3', 0)['to'], 'DELTA')

    def test_kursy_po_polnocy(self):  # AC4
        d = kierunek(self.r, '3', 0)
        kl = self.r['days']['2026-11-16']
        cent = d['dep'][kl][2]
        self.assertIn([24 * 60 + 5, 0], cent)

    def test_zajezdnia_z_dopiskiem(self):  # Q3
        d = kierunek(self.r, '3', 0)
        kl = self.r['days']['2026-11-16']
        hi = d['hs'].index('Zajezdnia GAJ')
        self.assertIn([22 * 60, hi], d['dep'][kl][0])
        # na Becie kurs zjazdowy nie zabiera pasażerów (pickup_type=1)
        self.assertNotIn([22 * 60 + 2, hi], d['dep'][kl][1])

    def test_typy_dni_i_swieto(self):  # AC2, edge case święta
        days = self.r['days']
        self.assertEqual(days['2026-11-16'], days['2026-11-17'])
        self.assertEqual(days['2026-11-18'], days['2026-11-21'])  # środa świąteczna = rozkład weekendowy
        self.assertNotEqual(days['2026-11-16'], days['2026-11-21'])
        labels = self.r['labels']
        self.assertEqual(labels[days['2026-11-16']], 'pon.-pt.')
        self.assertEqual(labels[days['2026-11-21']], 'sob.-niedz. + święta')
        self.assertEqual(days['2026-11-25'], days['2026-11-16'])  # zwykła środa

    def test_slupki_tej_samej_nazwy(self):  # A5, GPS
        cent = next(s for s in self.r['stops'] if s['n'] == 'Cent')
        self.assertEqual(len(cent['p']), 2)

    def test_walidacja_przechodzi(self):
        zb.waliduj(self.r)

    def test_okres_waznosci(self):  # AC13
        self.assertEqual((self.r['validFrom'], self.r['validTo']), ('2026-11-16', '2026-11-29'))


class Zapis(unittest.TestCase):
    def test_blad_nie_nadpisuje_wyniku(self):  # AC15
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'rozklad.json')
            with open(out, 'w') as f:
                f.write('{"stary": true}')
            zly = os.path.join(tmp, 'zly.zip')
            with zipfile.ZipFile(zly, 'w') as z:
                z.writestr('feed_info.txt', 'x')
            self.assertEqual(zb.main(['--zip', zly, '--out', out]), 1)
            self.assertEqual(json.load(open(out)), {'stary': True})

    def test_dobry_zapis(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp, out = os.path.join(tmp, 'g.zip'), os.path.join(tmp, 'r.json')
            open(zp, 'wb').write(zip_fikstury())
            self.assertEqual(zb.main(['--zip', zp, '--out', out]), 0)
            self.assertEqual(json.load(open(out))['v'], 1)


if __name__ == '__main__':
    unittest.main()
