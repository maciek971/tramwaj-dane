# tramwaj-dane

Lekki rozkład jazdy **wszystkich linii MPK Wrocław** (137 linii, tramwaje i autobusy) dla aplikacji „MPK” na telefon z KaiOS.

- `wersja.json`: <https://cdn.jsdelivr.net/gh/maciek971/tramwaj-dane@dane/wersja.json> (ok. 200 B). Zawiera `source`, ważność i ścieżkę paczki.
- Paczka: `https://cdn.jsdelivr.net/gh/maciek971/tramwaj-dane@dane/v/<source>/mpk.json` (ok. 2,4 MB, ok. 170 KB po kompresji).
- Gałąź `dane` jest odtwarzana przy każdej publikacji (jeden commit). Trzyma bieżącą i poprzednią paczkę oraz stary `rozklad.json` (format v1, linie 3 i 5, już nieaktualizowany).
- Odświeżane codziennie o 03:30 UTC przez GitHub Actions (`.github/workflows/rozklad.yml`). Gdy rozkład się nie zmienił albo skrypt zgłosi błąd, nic nie jest publikowane.
- Dlaczego jsDelivr, a nie GitHub Pages: KaiOS 2.5 (Gecko 48) nie ufa certyfikatom Let's Encrypt, których używają github.io i raw.githubusercontent.com.

## Źródło danych

Otwarte Dane Wrocławia, zbiór [Rozkład jazdy transportu publicznego](https://open-data.cui.wroclaw.pl/hdb/metadane/13/) (GTFS), licencja **CC0 1.0**. Skrypt bierze najnowszy plik, który już obowiązuje (data w nazwie ≤ dziś).

## Uruchomienie

```bash
python3 zbuduj_rozklad.py --out public
```

```bash
python3 -m unittest
```

Wymaga tylko Pythona 3 (biblioteka standardowa).

## Format v2

- `days`: data → klucz rozkładu. `labels`: klucz → typ dnia („pon.-czw.”).
- `lines`: `{id, g, opis}`, gdzie `g` to grupa `T` (tramwaj), `A` (autobus) albo `N` (nocny).
- `stops`: słupki `{c: stop_code, n: nazwa, nr: numer słupka, p: [lat, lon], k: opis kierunku, l: linie}`.
- `dirs[linia]`: kierunki `{dir, to, s: indeksy słupków, hs: kursy skrócone, dep}`.
  - `dep[klucz]` to lista na każdy słupek z odjazdami zakodowanymi jako różnice minut od poprzedniego (pierwsza wartość to minuty od północy, mogą przekraczać 1440).
  - Wartość ujemna `-(różnica*16 + indeks_hs)` oznacza kurs skrócony (np. do zajezdni).
  - Wartość tekstowa (np. `"R1"`) oznacza ten sam rozkład co wskazany klucz.
