#!/usr/bin/env python3
"""Buduje lekki rozkład linii tramwajowych 3 i 5 (MPK Wrocław) z miejskiego GTFS.

Źródło: Otwarte Dane Wrocławia, zbiór „Rozkład jazdy transportu publicznego” (CC0 1.0)
https://open-data.cui.wroclaw.pl/hdb/metadane/13/

Użycie:
  python3 zbuduj_rozklad.py --out public/rozklad.json            # pobiera plik ważny dziś
  python3 zbuduj_rozklad.py --zip gtfs.zip --out rozklad.json    # z lokalnego pliku
  python3 zbuduj_rozklad.py --data 2026-11-20 --out rozklad.json # wybór pliku na inną datę

Tylko biblioteka standardowa. Przy błędzie kończy się kodem 1 i nie nadpisuje --out.
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

LINIE = ('3', '5')
LISTA_URL = 'https://open-data.cui.wroclaw.pl/hdb/ft/6/'
POBIERZ_URL = 'https://open-data.cui.wroclaw.pl/hdb/download/%s/'
UA = {'User-Agent': 'tramwaj-rozklad/1.0 (+https://github.com/maciek971/tramwaj-dane)'}
DNI = ['pon.', 'wt.', 'śr.', 'czw.', 'pt.', 'sob.', 'niedz.']


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
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
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


def zbuduj(z):
    feed = czytaj(z, 'feed_info.txt')[0]
    trasy = {r['route_id']: r['route_short_name'] for r in czytaj(z, 'routes.txt') if r['route_short_name'] in LINIE}
    kursy = {t['trip_id']: t for t in czytaj(z, 'trips.txt') if t['route_id'] in trasy}
    przystanki = {s['stop_id']: s for s in czytaj(z, 'stops.txt')}
    kalendarz = czytaj(z, 'calendar.txt')
    try:
        wyjatki = czytaj(z, 'calendar_dates.txt')
    except KeyError:
        wyjatki = []

    czasy = defaultdict(list)
    with z.open('stop_times.txt') as f:
        for s in csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig')):
            if s['trip_id'] in kursy:
                czasy[s['trip_id']].append(s)
    for v in czasy.values():
        v.sort(key=lambda s: int(s['stop_sequence']))

    # kierunki: (linia, direction_id) -> główny wariant = najczęstsza sekwencja przystanków do najczęstszej pętli
    grupy = defaultdict(list)
    for tid, t in kursy.items():
        grupy[(trasy[t['route_id']], int(t['direction_id']))].append(tid)

    stopy_idx, stopy = {}, []

    def idx_przystanku(nazwa):
        if nazwa not in stopy_idx:
            stopy_idx[nazwa] = len(stopy)
            stopy.append({'n': nazwa, 'p': []})
        return stopy_idx[nazwa]

    kierunki = []
    for (linia, kier) in sorted(grupy):
        tids = grupy[(linia, kier)]
        petla = Counter(kursy[t]['trip_headsign'] for t in tids).most_common(1)[0][0]
        wzorce = Counter()
        for t in tids:
            if kursy[t]['trip_headsign'] == petla:
                nazwy = []
                for s in czasy[t]:
                    n = przystanki[s['stop_id']]['stop_name']
                    if not nazwy or nazwy[-1] != n:
                        nazwy.append(n)
                wzorce[tuple(nazwy)] += 1
        wzorzec = list(wzorce.most_common(1)[0][0])
        trasa = wzorzec[:-1]  # z pętli końcowej w tym kierunku nikt nie odjeżdża
        poz = {}
        for i, n in enumerate(trasa):
            poz.setdefault(n, i)
        kierunki.append({'line': linia, 'dir': kier, 'to': petla.upper(), 'trasa': trasa, 'poz': poz,
                         'tids': tids, 'petla': petla})

    # odjazdy per serwis, potem per typ dnia (zbiór aktywnych serwisów)
    def odjazdy_kierunku(k, serwisy):
        hs = ['']
        dep = [[] for _ in k['trasa']]
        for t in k['tids']:
            if kursy[t]['service_id'] not in serwisy:
                continue
            h = kursy[t]['trip_headsign']
            hi = 0
            if h != k['petla']:
                if h not in hs:
                    hs.append(h)
                hi = hs.index(h)
            for s in czasy[t]:
                if s.get('pickup_type') == '1':
                    continue
                n = przystanki[s['stop_id']]['stop_name']
                if n in k['poz']:
                    dep[k['poz'][n]].append([minuty(s['departure_time']), hi])
        for d in dep:
            d.sort()
        return dep, hs

    start, koniec = data_gtfs(feed['feed_start_date']), data_gtfs(feed['feed_end_date'])
    dni, klucze, tresci = OrderedDict(), {}, []
    d = start
    while d <= koniec:
        serw = aktywne_serwisy(kalendarz, wyjatki, d)
        if serw not in klucze:
            wyniki = [odjazdy_kierunku(k, serw) for k in kierunki]
            sygn = json.dumps(wyniki, separators=(',', ':'))
            if sygn in tresci:
                klucze[serw] = 'R%d' % (tresci.index(sygn) + 1)
            else:
                tresci.append(sygn)
                klucze[serw] = 'R%d' % len(tresci)
        dni[d.isoformat()] = klucze[serw]
        d += dt.timedelta(days=1)

    # Etykiety: typowy rozkład każdego dnia tygodnia (większość; remis -> najpóźniejsza data).
    # Daty z innym rozkładem niż typowy dla swojego dnia tygodnia to święta.
    # (MPK koduje święta także w calendar.txt, np. 11.11 jako dodatkowy dzień serwisu niedzielnego.)
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

    wyniki_klucza = {'R%d' % (i + 1): json.loads(s) for i, s in enumerate(tresci)}
    dirs = []
    for ki, k in enumerate(kierunki):
        hs_all = ['']
        dep = {}
        for kl, wyn in wyniki_klucza.items():
            dk, hsk = wyn[ki]
            mapa = []
            for h in hsk:
                if h not in hs_all:
                    hs_all.append(h)
                mapa.append(hs_all.index(h))
            dep[kl] = [[[m, mapa[h]] for m, h in lst] for lst in dk]
        dirs.append({'line': k['line'], 'dir': k['dir'], 'to': k['to'],
                     'stops': [idx_przystanku(n) for n in k['trasa']], 'dep': dep, 'hs': hs_all})

    for sid, s in przystanki.items():
        if s['stop_name'] in stopy_idx:
            p = [round(float(s['stop_lat']), 5), round(float(s['stop_lon']), 5)]
            if p not in stopy[stopy_idx[s['stop_name']]]['p']:
                stopy[stopy_idx[s['stop_name']]]['p'].append(p)

    return {
        'v': 1,
        'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'validFrom': start.isoformat(),
        'validTo': koniec.isoformat(),
        'days': dni,
        'labels': {kl: etykieta(*dni_klucza[kl]) for kl in wyniki_klucza},
        'stops': stopy,
        'dirs': dirs,
    }


def waliduj(r):
    linie = {d['line'] for d in r['dirs']}
    if linie != set(LINIE):
        raise ValueError('brak linii: %s' % sorted(set(LINIE) - linie))
    if r['validTo'] < r['validFrom']:
        raise ValueError('validTo < validFrom')
    for d in r['dirs']:
        for kl in r['labels']:
            if not any(d['dep'].get(kl)):
                raise ValueError('linia %s kier. %s: brak odjazdów dla %s' % (d['line'], d['dir'], kl))


def zapisz(r, out):
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, out)


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    a.add_argument('--zip')
    a.add_argument('--data', help='RRRR-MM-DD, domyślnie dziś')
    a.add_argument('--out', required=True)
    args = a.parse_args(argv)
    try:
        if args.zip:
            with open(args.zip, 'rb') as f:
                dane = f.read()
            zrodlo = os.path.basename(args.zip)
        else:
            dzis = dt.date.fromisoformat(args.data) if args.data else dt.date.today()
            data, ident = wybierz_plik(lista_plikow(pobierz(LISTA_URL).decode('utf-8')), dzis)
            dane = pobierz(POBIERZ_URL % ident)
            zrodlo = 'OtwartyWroclaw_rozklad_jazdy_GTFS_%s' % data.strftime('%d%m%Y')
        r = zbuduj(zipfile.ZipFile(io.BytesIO(dane)))
        r['source'] = zrodlo
        waliduj(r)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        zapisz(r, args.out)
    except Exception as e:  # jeden komunikat dla workflow, plik wynikowy nietknięty
        print('BŁĄD: %s' % e, file=sys.stderr)
        return 1
    n = sum(len(x) for d in r['dirs'] for v in d['dep'].values() for x in v)
    print('OK %s: %s..%s, %d odjazdów, %d przystanków, typy dni: %s' % (
        r['source'], r['validFrom'], r['validTo'], n, len(r['stops']), r['labels']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
