# Dataset — Robbery Police-Report Narratives (PT-BR), de-characterized & annotated

**File:** `bos_anonimizacao_CAP_descaracterizado.xlsx` · **Records:** 996 · **Language:** Brazilian Portuguese

The first Brazilian-Portuguese dataset annotated for **anonymization (de-identification)**
in the **police domain** (robbery police reports — *boletins de ocorrência*, BOs).
It supports the paper *Local Anonymization of Free-Text Robbery Police Reports in
Brazilian Portuguese* (KDMiLe).

## What it contains
Each row is one robbery BO **narrative** (the free-text "Histórico" field) plus an
entity-level **gold standard** of personally identifiable information (PII).

| Column | Description |
|---|---|
| `Seq` | Record id |
| `Texto Descaracterizado` | Publishable narrative: real names/locations replaced by **plausible fictitious** values |
| `Nome(s)` | Person names (victims, witnesses, officers, suspects) |
| `Localizações (s)` | Locations (neighborhoods, streets, cities, POIs) |
| `Documento(s)` | Natural-person documents (CPF/RG/CNH/IMEI) |
| `Emplacamento (s)` | License plates |
| `Telefone (s)` | Phone numbers |
| `Email (s) e contas` | E-mails / social accounts |
| `N° da VTR` | Patrol-car codes |
| `Vulgo(s)/Apelido(s)` | Nicknames |

Annotated entities are listed **verbatim** from `Texto Descaracterizado` (separated by `;`),
so annotation and text correspond exactly. Distribution (entities): Locations 729,
Name 502, Document 65, Plate 45, Phone 11, VTR 5, E-mail 1, Nickname 1.

> ⚠️ **No original text is published.** This file contains only the **de-characterized**
> narrative (fictitious values) and the annotations. The column with the original report
> text was intentionally removed.

## How it was built
De-characterization and annotation were performed by **four public-security experts**
from the State Public Security Department, coordinated by a **Military Police captain**
(head of the analysis and planning section). Each BO was de-characterized and annotated
**individually**; the gold standard was subsequently **audited** (audit log). Institutional
codes (IML, NOC, BOPM, CNJ case numbers) mixed into the Document column were reclassified
as "hygiene" and excluded from the personal-PII counts.

## Intended use & limitations
- **Use:** benchmarking PT-BR anonymization/NER, studying police-narrative writing, and
  building public-safety tools.
- **Annotation is disjoint** (one expert per record) — no inter-annotator agreement.
- Single jurisdiction/period; style/vocabulary may differ across forces.
- Rare types (Phone, VTR, E-mail, Nickname) have few instances; per-type metrics on these
  are unstable.

## License
**CC BY 4.0** — free to use and share with attribution (cite the paper). See repository README.
