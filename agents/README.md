# Baarn Raadsinformatie Agents

Deze directory bevat de agent definities voor de Baarn Raadsinformatie MCP Server.

## Agents Overzicht (25 agents)

### Meta & Coördinatie
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `orchestrator` | meta | Coördineert andere agents voor complexe vragen |

### Analyse & Onderzoek
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `vergadering-analist` | analyse | Analyseert vergaderingen en geeft inzichten |
| `stemgedrag-analist` | analyse | Analyseert stempatronen per partij/raadslid |
| `document-zoeker` | zoeken | Doorzoekt politieke documenten op inhoud |
| `beleids-onderzoeker` | onderzoek | Onderzoekt beleidsontwikkelingen en historie |
| `externe-onderzoeker` | onderzoek | Zoekt externe bronnen, vergelijkt met andere gemeenten |
| `multi-gemeente-zoeker` | onderzoek | Doorzoekt Notubiz van andere gemeenten |

### Monitoring & Tracking
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `besluit-tracker` | monitoring | Volgt besluiten en hun voortgang |
| `motie-tracker` | monitoring | Volgt moties en amendementen |
| `commissie-monitor` | monitoring | Monitort commissievergaderingen |
| `coalitie-monitor` | monitoring | Volgt uitvoering coalitieakkoord |
| `actiepunten-tracker` | monitoring | Volgt actiepunten en toezeggingen uit vergaderingen |
| `ingekomen-stukken-tracker` | monitoring | Volgt ingekomen stukken en brieven aan de raad |
| `toezeggingen-tracker` | monitoring | Volgt toezeggingen van college aan raad |
| `subsidie-tracker` | monitoring | Volgt subsidieaanvragen en -besluiten |

### Controle & Financiën
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `rekenkamer-analist` | controle | Analyseert beleid op effectiviteit en rechtmatigheid |
| `begrotings-analist` | financieel | Analyseert begrotingen en financiële besluiten |

### Assistentie
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `raadslid-assistent` | assistent | Ondersteunt raadsleden bij hun werk |
| `raadsvragen-assistent` | assistent | Helpt bij schriftelijke vragen aan college |
| `vergadering-voorbereiding` | voorbereiding | Bereidt vergaderingen voor met samenvattingen |
| `woo-assistent` | assistent | Helpt bij Woo-verzoeken (openbaarheid) |

### Publiek & Media
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `burger-informant` | publiek | Informeert burgers over lokale politiek |
| `journalist-assistent` | media | Ondersteunt journalisten bij onderzoek |

### Informatie & Organisatie
| Agent | Categorie | Beschrijving |
|-------|-----------|--------------|
| `personeel-informant` | informatie | Informeert over bestuurders, raadsleden en organisatie |
| `werkbezoek-verslag` | informatie | Beheert en verrijkt werkbezoek-verslagen |

## Agent Structuur

Elke agent is gedefinieerd in een YAML bestand met de volgende structuur:

```yaml
name: agent-naam
version: "1.0"
description: Korte beschrijving
category: categorie

metadata:
  author: Baarn Raadsinformatie
  language: nl
  domain: politiek

prompt:
  description: |
    Beschrijving voor MCP prompt listing
  arguments:
    - name: argument_naam
      description: Argument beschrijving
      required: false

system_prompt: |
  Uitgebreide instructies voor de agent...

examples:
  - user: "Voorbeeld vraag"
    assistant: "Voorbeeld antwoord"

related_agents:
  - andere-agent
```

## Agents Toevoegen

1. Maak een nieuw `.yaml` bestand in deze directory
2. Volg de structuur hierboven
3. De agent wordt automatisch geladen bij server start

## Beschikbare MCP Tools

Agents kunnen de volgende tools gebruiken:

- `get_meetings` - Vergaderingen ophalen
- `get_meeting_details` - Vergadering details
- `get_agenda_items` - Agendapunten ophalen
- `get_document` - Document ophalen
- `search_documents` - Keyword zoeken
- `semantic_search` - Semantisch zoeken
- `get_gremia` - Commissies ophalen
- `get_statistics` - Database statistieken
- `sync_data` - Data synchroniseren
- `add_annotation` - Notities toevoegen
- `get_annotations` - Notities ophalen
- `get_coalitie_akkoord` - Coalitieakkoord informatie en voortgang
- `update_coalitie_afspraak` - Status coalitie-afspraak updaten
- `add_visit_report` - Werkbezoek-verslag toevoegen
- `import_visit_reports` - Werkbezoek-verslagen importeren
- `list_visit_reports` - Werkbezoek-verslagen lijst
- `get_visit_report` - Werkbezoek-verslag details
- `search_visit_reports` - Werkbezoek-verslagen doorzoeken
- `update_visit_report` - Werkbezoek-verslag bijwerken
- `delete_visit_report` - Werkbezoek-verslag archiveren
- `link_visit_report_to_meeting` - Verslag koppelen aan vergadering
- `index_visit_reports` - Verslagdocumenten indexeren

## Categorieën

- **analyse** - Agents voor analyse en samenvatting
- **zoeken** - Agents voor zoeken en vinden
- **monitoring** - Agents voor tracking en monitoring
- **voorbereiding** - Agents voor vergadervoorbereiding
- **assistent** - Algemene assistent agents
- **publiek** - Agents voor burgers
- **onderzoek** - Agents voor diepgaand onderzoek (incl. extern/internet)
- **media** - Agents voor journalisten/media
- **controle** - Agents voor rekenkamer-achtige controle en evaluatie

## Testen

Test een agent via de MCP client:

```bash
# List alle agents
python -c "from agents import get_agent_loader; print([a.name for a in get_agent_loader().load_agents().values()])"

# Test specifieke agent
python agents/__init__.py
```
