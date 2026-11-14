"""Testy skryptu budującego rozkład (format v2). Uruchomienie: python3 -m unittest"""
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


def czytaj_json(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def kierunek(r, linia, kier):
    return next(d for d in r['dirs'][linia] if d['dir'] == kier)


def nazwy(r, d):
    return [r['stops'][i]['n'] for i in d['s']]


def odjazdy(r, d, kl, i):
    v = d['dep'][kl]
    if isinstance(v, str):
        v = d['dep'][v]
    return zb.dekoduj(v[i])


class WyborPliku(unittest.TestCase):
    HTML = ('<td>OtwartyWroclaw_rozklad_jazdy_GTFS_16112026</td><a href="/hdb/download/162/">'
            '<td>OtwartyWroclaw_rozklad_jazdy_GTFS_07112026</td><a href="/hdb/download/160/">'
            '<td>OtwartyWroclaw_rozklad_jazdy_GTFS_03112026</td><a href="/hdb/download/156/">')

    def test_lista(self):
        self.assertEqual(zb.lista_plikow(self.HTML)[0], (dt.date(2026, 11, 16), '162'))
        self.assertEqual(len(zb.lista_plikow(self.HTML)), 3)

    def test_nie_bierze_pliku_z_przyszlosci(self):
        pliki = zb.lista_plikow(self.HTML)
        self.assertEqual(zb.wybierz_plik(pliki, dt.date(2026, 11, 14))[1], '160')
        self.assertEqual(zb.wybierz_plik(pliki, dt.date(2026, 11, 16))[1], '162')

    def test_brak_pliku(self):
        with self.assertRaises(ValueError):
            zb.wybierz_plik(zb.lista_plikow(self.HTML), dt.date(2026, 1, 1))


class Kodowanie(unittest.TestCase):
    def test_koduj_dekoduj(self):
        lista = [[300, 0], [312, 0], [312, 2], [1450, 1]]
        self.assertEqual(zb.dekoduj(zb.koduj(lista)), lista)
        self.assertEqual(zb.koduj([[300, 0], [305, 0]]), [300, 5])

    def test_nazwa_i_numer_slupka(self):
        self.assertEqual(zb.nazwa_i_nr('GALERIA DOMINIKAŃSKA 07'), ('GALERIA DOMINIKAŃSKA', '07'))
        self.assertEqual(zb.nazwa_i_nr('Rynek'), ('Rynek', ''))
        self.assertEqual(zb.nazwa_i_nr('Plac 1 Maja'), ('Plac 1 Maja', ''))


class Budowa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = zb.zbuduj(zipfile.ZipFile(io.BytesIO(zip_fikstury())))

    def test_wszystkie_linie_i_grupy(self):  # AC1
        self.assertEqual([l['id'] for l in self.r['lines']], ['3', '5', '116', '240'])
        g = {l['id']: (l['g'], l['opis']) for l in self.r['lines']}
        self.assertEqual(g['3'], ('T', ''))
        self.assertEqual(g['116'], ('A', 'strefowa'))  # spacja w numerze przycięta
        self.assertEqual(g['240'], ('N', ''))

    def test_kolejnosc_przystankow_bez_petli(self):  # AC3
        self.assertEqual(nazwy(self.r, kierunek(self.r, '3', 0)), ['Alfa', 'Beta', 'CENT'])
        self.assertEqual(nazwy(self.r, kierunek(self.r, '3', 1)), ['Delta', 'CENT', 'Beta'])
        self.assertEqual(kierunek(self.r, '3', 0)['to'], 'DELTA')

    def test_slupki_z_numerem_i_opisem(self):  # A4
        cent = [s for s in self.r['stops'] if s['n'] == 'CENT']
        self.assertEqual(sorted(s['nr'] for s in cent), ['01', '02'])
        c1 = next(s for s in cent if s['nr'] == '01')
        self.assertEqual(c1['c'], '103')
        self.assertEqual(c1['l'], ['3', '5', '116', '240'])
        self.assertTrue(c1['k'].startswith('→ '))

    def test_kursy_po_polnocy(self):  # AC3/AC4
        d = kierunek(self.r, '3', 0)
        kl = self.r['days']['2026-11-16']
        self.assertIn([24 * 60 + 5, 0], odjazdy(self.r, d, kl, 2))
        nocna = kierunek(self.r, '240', 0)
        self.assertEqual(odjazdy(self.r, nocna, kl, 0), [[25 * 60 + 10, 0]])

    def test_zajezdnia_z_dopiskiem(self):
        d = kierunek(self.r, '3', 0)
        kl = self.r['days']['2026-11-16']
        hi = d['hs'].index('Zajezdnia GAJ')
        self.assertIn([22 * 60, hi], odjazdy(self.r, d, kl, 0))
        self.assertNotIn([22 * 60 + 2, hi], odjazdy(self.r, d, kl, 1))  # pickup_type=1

    def test_typy_dni_i_swieto(self):
        days = self.r['days']
        self.assertEqual(days['2026-11-16'], days['2026-11-17'])
        self.assertEqual(days['2026-11-18'], days['2026-11-21'])
        self.assertEqual(days['2026-11-25'], days['2026-11-16'])
        labels = self.r['labels']
        self.assertEqual(labels[days['2026-11-16']], 'pon.-pt.')
        self.assertEqual(labels[days['2026-11-21']], 'sob.-niedz. + święta')

    def test_alias_identycznego_rozkladu(self):
        # linia 116 nie kursuje w weekend -> pusty rozkład; linia 3 ma różne rozkłady -> brak aliasu
        d3 = kierunek(self.r, '3', 0)
        self.assertTrue(all(isinstance(v, list) for v in d3['dep'].values()))
        r = {'dep': {'R1': [[1, 2]], 'R2': 'R1'}}
        self.assertEqual(odjazdy(None, r, 'R2', 0), [[1, 0], [3, 0]])

    def test_walidacja(self):
        zb.waliduj(self.r, min_linii=4)
        with self.assertRaises(ValueError):
            zb.waliduj(self.r)  # domyślnie >= 100 linii

    def test_okres_waznosci(self):
        self.assertEqual((self.r['validFrom'], self.r['validTo']), ('2026-11-16', '2026-11-29'))


class Zapis(unittest.TestCase):
    def test_blad_nie_nadpisuje_wyniku(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'public')
            os.makedirs(out)
            with open(os.path.join(out, 'wersja.json'), 'w') as f:
                f.write('{"stary": true}')
            zly = os.path.join(tmp, 'zly.zip')
            with zipfile.ZipFile(zly, 'w') as z:
                z.writestr('feed_info.txt', 'x')
            self.assertEqual(zb.main(['--zip', zly, '--out', out]), 1)
            self.assertEqual(czytaj_json(os.path.join(out, 'wersja.json')), {'stary': True})

    def test_paczka_i_wersja(self):  # AC10
        with tempfile.TemporaryDirectory() as tmp:
            zp, out = os.path.join(tmp, 'OtwartyWroclaw_rozklad_jazdy_GTFS_16112026.zip'), os.path.join(tmp, 'public')
            with open(zp, 'wb') as f:
                f.write(zip_fikstury())
            self.assertEqual(zb.main(['--zip', zp, '--out', out, '--min-linii', '4']), 0)
            w = czytaj_json(os.path.join(out, 'wersja.json'))
            self.assertEqual(w['paczka'], 'v/OtwartyWroclaw_rozklad_jazdy_GTFS_16112026/mpk.json')
            self.assertEqual(w['rozmiar'], os.path.getsize(os.path.join(out, 'mpk.json')))
            self.assertEqual(czytaj_json(os.path.join(out, 'mpk.json'))['v'], 2)


if __name__ == '__main__':
    unittest.main()
