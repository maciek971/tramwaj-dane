#!/usr/bin/env python3
"""Buduje lekki rozkład wszystkich linii MPK Wrocław (format v2) z miejskiego GTFS.

Źródło: Otwarte Dane Wrocławia, zbiór „Rozkład jazdy transportu publicznego” (CC0 1.0)
https://open-data.cui.wroclaw.pl/hdb/metadane/13/

Użycie:
  python3 zbuduj_rozklad.py --out public                # pobiera plik ważny dziś -> public/mpk.json + public/wersja.json
  python3 zbuduj_rozklad.py --zip gtfs.zip --out public # z lokalnego pliku
  python3 zbuduj_rozklad.py --paczka ../tramwaj/dane/mpk.json   # sama paczka (zapas w aplikacji)
  python3 zbuduj_rozklad.py --data 2026-11-20 --out public      # wybór pliku na inną datę

Tylko biblioteka standardowa. Przy błędzie kończy się kodem 1 i niczego nie nadpisuje.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from collections import Counter, OrderedDict, defaultdict

LISTA_URL = 'https://open-data.cui.wroclaw.pl/hdb/ft/6/'
POBIERZ_URL = 'https://open-data.cui.wroclaw.pl/hdb/download/%s/'
UA = {'User-Agent': 'tramwaj-rozklad/2.0 (+https://github.com/maciek971/tramwaj-dane)'}
DNI = ['pon.', 'wt.', 'śr.', 'czw.', 'pt.', 'sob.', 'niedz.']
MIN_LINII = 100
NR_SLUPKA = re.compile(r'^(.*\S)\s+(\d{2})$')  # 'GALERIA DOMINIKAŃSKA 07' -> nazwa + numer słupka


def nazwa_i_nr(n):
    m = NR_SLUPKA.match(n.strip())
    return (m.group(1), m.group(2)) if m else (n.strip(), '')


def koduj(lista):
    """[[minuty, hs], ...] posortowane -> różnice minut; kurs skrócony (hs>0) jako -(różnica*16+hs)."""
    out, prev = [], 0
    for m, h in lista:
        d = m - prev
        prev = m
        out.append(d if h == 0 else -(d * 16 + h))
    return out


def dekoduj(lista):
    out, m = [], 0
    for v in lista:
        if v >= 0:
            m += v
            out.append([m, 0])
        else:
            m += (-v) // 16
            out.append([m, (-v) % 16])
    return out
# route_type2_id -> (grupa, opis); grupy: T tramwaj, A autobus, N nocny
TYPY = {'30': ('A', ''), '31': ('T', ''), '32': ('A', 'okresowa'), '34': ('A', 'podmiejska'),
        '35': ('A', 'pospieszna'), '39': ('A', 'strefowa'), '40': ('N', '')}


# ---------- wybór i pobranie pliku ----------

def lista_plikow(html):
    """[(data_startu, id_pobrania)] z HTML strony z listą plików GTFS."""
    out = []
    for d, i in re.findall(r'OtwartyWroclaw_rozklad_jazdy_GTFS_(\d{8}).*?/hdb/download/(\d+)/', html, re.S):
        out.append((dt.date(int(d[4:]), int(d[2:4]), int(d[:2])), i))
    return out


def wybierz_plik(pliki, dzis):
    """Najnowszy plik z datą startu <= dziś (nowsze jeszcze nie obowiązują)."""
    ok = [p for p in pliki if p[0] <= dzis]
    if not ok:
        raise ValueError('brak pliku GTFS ważnego na %s' % dzis)
    return max(ok)


def pobierz(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        return r.read()


# ---------- przetwarzanie GTFS ----------

def czytaj(z, nazwa):
    with z.open(nazwa) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig')))


def minuty(hhmmss):
    h, m = hhmmss.split(':')[:2]
    return int(h) * 60 + int(m)


def data_gtfs(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def aktywne_serwisy(kalendarz, wyjatki, dzien):
    akt = set()
    for c in kalendarz:
        if data_gtfs(c['start_date']) <= dzien <= data_gtfs(c['end_date']):
            if c[['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][dzien.weekday()]] == '1':
                akt.add(c['service_id'])
    for w in wyjatki:
        if data_gtfs(w['date']) == dzien:
            if w['exception_type'] == '1':
                akt.add(w['service_id'])
            elif w['exception_type'] == '2':
                akt.discard(w['service_id'])
    return frozenset(akt)


def etykieta(dni_tyg, swieto):
    """Zbiór numerów dni tygodnia -> 'pon.-czw.', 'pt.', 'sob.'..."""
    dni = sorted(dni_tyg)
    czesci, i = [], 0
    while i < len(dni):
        j = i
        while j + 1 < len(dni) and dni[j + 1] == dni[j] + 1:
            j += 1
        czesci.append(DNI[dni[i]] if i == j else '%s-%s' % (DNI[dni[i]], DNI[dni[j]]))
        i = j + 1
    txt = ', '.join(czesci)
    if swieto:
        txt = (txt + ' + święta') if txt else 'święta'
    return txt


def klucz_linii(lid):
    """Sortowanie: tramwaje i autobusy numerycznie, litery na końcu swojej długości."""
    return (0, int(lid), '') if lid.isdigit() else (1, 0, lid)


def zbuduj(z):
    feed = czytaj(z, 'feed_info.txt')[0]
    trasy = {}
    linie = {}
    for r in czytaj(z, 'routes.txt'):
        lid = r['route_short_name'].strip()
        typ = r.get('route_type2_id', '').strip()
        g, opis = TYPY.get(typ, ('T' if r.get('route_type') == '0' else 'A', ''))
        trasy[r['route_id']] = lid
        linie[lid] = {'id': lid, 'g': g, 'opis': opis}
    kursy = {t['trip_id']: t for t in czytaj(z, 'trips.txt') if t['route_id'] in trasy}
    slupki = {s['stop_id']: s for s in czytaj(z, 'stops.txt')}
    kalendarz = czytaj(z, 'calendar.txt')
    try:
        wyjatki = czytaj(z, 'calendar_dates.txt')
    except KeyError:
        wyjatki = []

    # kurs -> [(kolejność, stop_id, minuty, wsiadanie)]; krotki zamiast słowników (1 mln wierszy)
    czasy = defaultdict(list)
    with z.open('stop_times.txt') as f:
        for s in csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig')):
            if s['trip_id'] in kursy:
                czasy[s['trip_id']].append((int(s['stop_sequence']), s['stop_id'], minuty(s['departure_time']),
                                            s.get('pickup_type') != '1'))
    for v in czasy.values():
        v.sort()

    grupy = defaultdict(list)
    for tid, t in kursy.items():
        if czasy.get(tid):
            grupy[(trasy[t['route_id']], int(t['direction_id']))].append(tid)

    # kierunek: wzorzec = najczęstsza sekwencja słupków kursów do najczęstszej pętli
    kierunki = []
    for (lid, kier) in sorted(grupy, key=lambda k: (klucz_linii(k[0]), k[1])):
        tids = grupy[(lid, kier)]
        petla = Counter(kursy[t]['trip_headsign'] for t in tids).most_common(1)[0][0]
        wzorce = Counter()
        for t in tids:
            if kursy[t]['trip_headsign'] == petla:
                seq = []
                for _, sid, _, _ in czasy[t]:
                    if not seq or seq[-1] != sid:
                        seq.append(sid)
                wzorce[tuple(seq)] += 1
        trasa = list(wzorce.most_common(1)[0][0])[:-1]  # z pętli końcowej nikt nie odjeżdża
        poz, poz_nazwy = {}, {}
        for i, sid in enumerate(trasa):
            poz.setdefault(sid, i)
            poz_nazwy.setdefault(nazwa_i_nr(slupki[sid]['stop_name'])[0], i)
        kierunki.append({'line': lid, 'dir': kier, 'to': petla.upper(), 'trasa': trasa, 'poz': poz,
                         'poz_nazwy': poz_nazwy, 'tids': tids, 'petla': petla})

    def odjazdy(k, serwisy):
        hs, dep = [''], [[] for _ in k['trasa']]
        for t in k['tids']:
            if kursy[t]['service_id'] not in serwisy:
                continue
            h = kursy[t]['trip_headsign']
            hi = 0
            if h != k['petla']:
                if h not in hs:
                    hs.append(h)
                hi = hs.index(h)
            for _, sid, m, wsiada in czasy[t]:
                if not wsiada:
                    continue
                i = k['poz'].get(sid)
                if i is None:  # kurs z innego słupka tej samej nazwy -> słupek wzorca
                    i = k['poz_nazwy'].get(nazwa_i_nr(slupki[sid]['stop_name'])[0])
                if i is not None:
                    dep[i].append([m, hi])
        for d in dep:
            d.sort()
        return dep, hs

    # typy dni: zbiór aktywnych serwisów, identyczne treści scalone w jeden klucz
    start, koniec = data_gtfs(feed['feed_start_date']), data_gtfs(feed['feed_end_date'])
    dni, klucze, tresci, wyniki = OrderedDict(), {}, [], {}
    d = start
    while d <= koniec:
        serw = aktywne_serwisy(kalendarz, wyjatki, d)
        if serw not in klucze:
            wyn = [odjazdy(k, serw) for k in kierunki]
            sygn = json.dumps(wyn, separators=(',', ':'))
            if sygn in tresci:
                klucze[serw] = 'R%d' % (tresci.index(sygn) + 1)
            else:
                tresci.append(sygn)
                klucze[serw] = 'R%d' % len(tresci)
                wyniki[klucze[serw]] = wyn
        dni[d.isoformat()] = klucze[serw]
        d += dt.timedelta(days=1)
    del tresci

    # etykiety: typowy rozkład dnia tygodnia (większość, remis -> późniejsza data); inne daty = święta
    typowy = {}
    for wd in range(7):
        daty = [(k, v) for k, v in dni.items() if dt.date.fromisoformat(k).weekday() == wd]
        if daty:
            licz = Counter(v for _, v in daty)
            najw = max(licz.values())
            typowy[wd] = [v for _, v in daty if licz[v] == najw][-1]
    dni_klucza = defaultdict(lambda: [set(), False])
    for wd, kl in typowy.items():
        dni_klucza[kl][0].add(wd)
    for k, v in dni.items():
        if typowy[dt.date.fromisoformat(k).weekday()] != v:
            dni_klucza[v][1] = True

    # słupki: tylko te, z których coś odjeżdża we wzorcach
    stop_idx, stops = {}, []
    serwuje = defaultdict(Counter)  # stop_id -> pętle
    linie_slupka = defaultdict(set)

    def idx(sid):
        if sid not in stop_idx:
            s = slupki[sid]
            stop_idx[sid] = len(stops)
            n, nr = nazwa_i_nr(s['stop_name'])
            stops.append({'c': (s.get('stop_code') or sid).strip(), 'n': n, 'nr': nr,
                          'p': [round(float(s['stop_lat']), 5), round(float(s['stop_lon']), 5)]})
        return stop_idx[sid]

    dirs = defaultdict(list)
    for ki, k in enumerate(kierunki):
        hs_all, dep = [''], {}
        poprz = {}  # treść -> klucz (alias identycznego rozkładu w tej linii)
        for kl in sorted(wyniki, key=lambda x: int(x[1:])):
            dk, hsk = wyniki[kl][ki]
            mapa = []
            for h in hsk:
                if h not in hs_all:
                    hs_all.append(h)
                mapa.append(hs_all.index(h))
            if len(hs_all) > 15:
                raise ValueError('linia %s: za dużo kursów skróconych (%d)' % (k['line'], len(hs_all)))
            lista = [koduj([[m, mapa[h]] for m, h in lst]) for lst in dk]
            sygn = json.dumps(lista, separators=(',', ':'))
            if sygn in poprz:
                dep[kl] = poprz[sygn]
            else:
                poprz[sygn] = kl
                dep[kl] = lista
        if not any(any(v) for v in dep.values() if isinstance(v, list)):
            continue
        for i, sid in enumerate(k['trasa']):
            if any(isinstance(v, list) and v[i] for v in dep.values()):
                serwuje[sid][k['to']] += 1
                linie_slupka[sid].add(k['line'])
        dirs[k['line']].append({'dir': k['dir'], 'to': k['to'], 's': [idx(s) for s in k['trasa']],
                                'dep': dep, 'hs': hs_all})

    for sid, i in stop_idx.items():
        pet = [p for p, _ in serwuje[sid].most_common(2)]
        stops[i]['k'] = ('→ ' + ', '.join(pet)) if pet else ''
        stops[i]['l'] = sorted(linie_slupka[sid], key=klucz_linii)

    return {
        'v': 2,
        'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'validFrom': start.isoformat(),
        'validTo': koniec.isoformat(),
        'days': dni,
        'labels': {kl: etykieta(*dni_klucza[kl]) for kl in wyniki},
        'lines': [linie[l] for l in sorted(dirs, key=klucz_linii)],
        'stops': stops,
        'dirs': dict(sorted(dirs.items(), key=lambda kv: klucz_linii(kv[0]))),
    }


def waliduj(r, min_linii=MIN_LINII):
    if len(r['lines']) < min_linii:
        raise ValueError('za mało linii: %d < %d' % (len(r['lines']), min_linii))
    if r['validTo'] < r['validFrom']:
        raise ValueError('validTo < validFrom')
    for lid, ds in r['dirs'].items():
        if not ds:
            raise ValueError('linia %s bez kierunków' % lid)
        for d in ds:
            if not any(isinstance(v, list) and any(v) for v in d['dep'].values()):
                raise ValueError('linia %s kier. %s: brak odjazdów' % (lid, d['dir']))


def zapisz_json(obj, out):
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, out)


def wersja(r, rozmiar):
    return {'v': 2, 'source': r['source'], 'validFrom': r['validFrom'], 'validTo': r['validTo'],
            'generated': r['generated'], 'paczka': 'v/%s/mpk.json' % r['source'], 'rozmiar': rozmiar}


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    a.add_argument('--zip')
    a.add_argument('--data', help='RRRR-MM-DD, domyślnie dziś')
    a.add_argument('--out', help='katalog na mpk.json i wersja.json')
    a.add_argument('--paczka', help='ścieżka pliku z samą paczką')
    a.add_argument('--min-linii', type=int, default=MIN_LINII)
    args = a.parse_args(argv)
    if not args.out and not args.paczka:
        a.error('podaj --out albo --paczka')
    try:
        if args.zip:
            with open(args.zip, 'rb') as f:
                dane = f.read()
            zrodlo = os.path.splitext(os.path.basename(args.zip))[0]
        else:
            dzis = dt.date.fromisoformat(args.data) if args.data else dt.date.today()
            data, ident = wybierz_plik(lista_plikow(pobierz(LISTA_URL).decode('utf-8')), dzis)
            dane = pobierz(POBIERZ_URL % ident)
            zrodlo = 'OtwartyWroclaw_rozklad_jazdy_GTFS_%s' % data.strftime('%d%m%Y')
        r = zbuduj(zipfile.ZipFile(io.BytesIO(dane)))
        r['source'] = zrodlo
        waliduj(r, args.min_linii)
        if args.paczka:
            os.makedirs(os.path.dirname(os.path.abspath(args.paczka)), exist_ok=True)
            zapisz_json(r, args.paczka)
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            p = os.path.join(args.out, 'mpk.json')
            zapisz_json(r, p)
            zapisz_json(wersja(r, os.path.getsize(p)), os.path.join(args.out, 'wersja.json'))
    except Exception as e:  # jeden komunikat dla workflow, pliki wynikowe nietknięte
        print('BŁĄD: %s' % e, file=sys.stderr)
        return 1
    n = sum(len(x) for ds in r['dirs'].values() for d in ds for v in d['dep'].values()
            if isinstance(v, list) for x in v)
    print('OK %s: %s..%s, %d linii, %d słupków, %d odjazdów, typy dni: %s' % (
        r['source'], r['validFrom'], r['validTo'], len(r['lines']), len(r['stops']), n, r['labels']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
