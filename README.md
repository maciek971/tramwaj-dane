# tramwaj-dane

Lekki rozkład jazdy tramwajów **3 i 5 MPK Wrocław** dla aplikacji na telefon z KaiOS.

- Wynik: <https://maciek971.github.io/tramwaj-dane/rozklad.json> (ok. 150 KB, ok. 20 KB po kompresji).
- Odświeżany codziennie o 03:30 UTC przez GitHub Actions (`.github/workflows/rozklad.yml`). Gdy skrypt zgłosi błąd, zostaje poprzedni plik.

## Źródło danych

Otwarte Dane Wrocławia, zbiór [Rozkład jazdy transportu publicznego](https://open-data.cui.wroclaw.pl/hdb/metadane/13/) (GTFS), licencja **CC0 1.0**. Skrypt bierze najnowszy plik, który już obowiązuje (data w nazwie ≤ dziś).

## Uruchomienie

```bash
python3 zbuduj_rozklad.py --out public/rozklad.json
```

```bash
python3 -m unittest
```

Wymaga tylko Pythona 3 (biblioteka standardowa).

## Format

`days` mapuje datę na klucz rozkładu, a `labels` klucz na typ dnia („pon.-pt.”). `stops` to nazwy przystanków ze współrzędnymi słupków. `dirs` to linia i kierunek z przystankami w kolejności przejazdu oraz odjazdami: `[minuty_od_północy, indeks_hs]`. Minuty mogą przekraczać 1440, gdy kurs jest po północy. Indeks `hs` różny od 0 oznacza kurs do zajezdni.
