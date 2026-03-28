"""
Apply the same data corrections to creches_portugal.csv that were applied to Supabase:
1. Canonical concelho → distrito mapping (fixes ~329 wrong distrito values)
2. Wrong concelho values from scraping artefacts (fake island names)
"""

import csv

INPUT = "creches_portugal.csv"
OUTPUT = "creches_portugal.csv"

# Canonical concelho → distrito mapping for mainland Portugal
CANONICAL = {
    'Abrantes': 'Santarém', 'Águeda': 'Aveiro', 'Aguiar da Beira': 'Guarda',
    'Alandroal': 'Évora', 'Albergaria-a-Velha': 'Aveiro', 'Albufeira': 'Faro',
    'Alcácer do Sal': 'Setúbal', 'Alcanena': 'Santarém', 'Alcobaça': 'Leiria',
    'Alcochete': 'Setúbal', 'Alcoutim': 'Faro', 'Alenquer': 'Lisboa',
    'Alfândega da Fé': 'Bragança', 'Alijó': 'Vila Real', 'Aljezur': 'Faro',
    'Aljustrel': 'Beja', 'Almada': 'Setúbal', 'Almeida': 'Guarda',
    'Almeirim': 'Santarém', 'Almodôvar': 'Beja', 'Alpiarça': 'Santarém',
    'Alter do Chão': 'Portalegre', 'Alvaiázere': 'Leiria', 'Alvito': 'Beja',
    'Amadora': 'Lisboa', 'Amarante': 'Porto', 'Amares': 'Braga',
    'Anadia': 'Aveiro', 'Ansião': 'Leiria', 'Arcos de Valdevez': 'Viana do Castelo',
    'Arganil': 'Coimbra', 'Armamar': 'Viseu', 'Arouca': 'Aveiro',
    'Arraiolos': 'Évora', 'Arronches': 'Portalegre', 'Arruda dos Vinhos': 'Lisboa',
    'Aveiro': 'Aveiro', 'Avis': 'Portalegre', 'Azambuja': 'Lisboa',
    'Baião': 'Porto', 'Barcelos': 'Braga', 'Barrancos': 'Beja',
    'Barreiro': 'Setúbal', 'Batalha': 'Leiria', 'Beja': 'Beja',
    'Belmonte': 'Castelo Branco', 'Benavente': 'Santarém', 'Bombarral': 'Leiria',
    'Borba': 'Évora', 'Boticas': 'Vila Real', 'Braga': 'Braga',
    'Bragança': 'Bragança', 'Cabeceiras de Basto': 'Braga', 'Cadaval': 'Lisboa',
    'Caldas da Rainha': 'Leiria', 'Caminha': 'Viana do Castelo',
    'Campo Maior': 'Portalegre', 'Cantanhede': 'Coimbra',
    'Carrazeda de Ansiães': 'Bragança', 'Carregal do Sal': 'Viseu',
    'Cartaxo': 'Santarém', 'Cascais': 'Lisboa', 'Castanheira de Pêra': 'Leiria',
    'Castelo Branco': 'Castelo Branco', 'Castelo de Paiva': 'Aveiro',
    'Castelo de Vide': 'Portalegre', 'Castro Daire': 'Viseu',
    'Castro Marim': 'Faro', 'Castro Verde': 'Beja', 'Celorico da Beira': 'Guarda',
    'Celorico de Basto': 'Braga', 'Chamusca': 'Santarém', 'Chaves': 'Vila Real',
    'Cinfães': 'Viseu', 'Coimbra': 'Coimbra', 'Condeixa-a-Nova': 'Coimbra',
    'Constância': 'Santarém', 'Coruche': 'Santarém', 'Covilhã': 'Castelo Branco',
    'Crato': 'Portalegre', 'Cuba': 'Beja', 'Elvas': 'Portalegre',
    'Entroncamento': 'Santarém', 'Espinho': 'Aveiro', 'Esposende': 'Braga',
    'Estarreja': 'Aveiro', 'Estremoz': 'Évora', 'Évora': 'Évora',
    'Fafe': 'Braga', 'Faro': 'Faro', 'Felgueiras': 'Porto',
    'Ferreira do Alentejo': 'Beja', 'Ferreira do Zêzere': 'Santarém',
    'Figueira da Foz': 'Coimbra', 'Figueira de Castelo Rodrigo': 'Guarda',
    'Figueiró dos Vinhos': 'Leiria', 'Fornos de Algodres': 'Guarda',
    'Freixo de Espada à Cinta': 'Bragança', 'Fronteira': 'Portalegre',
    'Fundão': 'Castelo Branco', 'Gavião': 'Portalegre', 'Góis': 'Coimbra',
    'Golegã': 'Santarém', 'Gondomar': 'Porto', 'Gouveia': 'Guarda',
    'Grândola': 'Setúbal', 'Guarda': 'Guarda', 'Guimarães': 'Braga',
    'Idanha-a-Nova': 'Castelo Branco', 'Ílhavo': 'Aveiro', 'Lagoa': 'Faro',
    'Lagos': 'Faro', 'Lamego': 'Viseu', 'Leiria': 'Leiria', 'Lisboa': 'Lisboa',
    'Loulé': 'Faro', 'Loures': 'Lisboa', 'Lourinhã': 'Lisboa',
    'Lousã': 'Coimbra', 'Lousada': 'Porto', 'Mação': 'Santarém',
    'Macedo de Cavaleiros': 'Bragança', 'Mafra': 'Lisboa', 'Maia': 'Porto',
    'Mangualde': 'Viseu', 'Manteigas': 'Guarda', 'Marco de Canaveses': 'Porto',
    'Marinha Grande': 'Leiria', 'Marvão': 'Portalegre', 'Matosinhos': 'Porto',
    'Mealhada': 'Aveiro', 'Mêda': 'Guarda', 'Melgaço': 'Viana do Castelo',
    'Mértola': 'Beja', 'Mesão Frio': 'Vila Real', 'Mira': 'Coimbra',
    'Miranda do Corvo': 'Coimbra', 'Miranda do Douro': 'Bragança',
    'Mirandela': 'Bragança', 'Mogadouro': 'Bragança', 'Moimenta da Beira': 'Viseu',
    'Moita': 'Setúbal', 'Monção': 'Viana do Castelo', 'Monchique': 'Faro',
    'Mondim de Basto': 'Vila Real', 'Monforte': 'Portalegre',
    'Montalegre': 'Vila Real', 'Montemor-o-Novo': 'Évora',
    'Montemor-o-Velho': 'Coimbra', 'Montijo': 'Setúbal', 'Mora': 'Évora',
    'Mortágua': 'Viseu', 'Moura': 'Beja', 'Mourão': 'Évora',
    'Murça': 'Vila Real', 'Murtosa': 'Aveiro', 'Nazaré': 'Leiria',
    'Nelas': 'Viseu', 'Nisa': 'Portalegre', 'Óbidos': 'Leiria',
    'Odemira': 'Beja', 'Odivelas': 'Lisboa', 'Oeiras': 'Lisboa',
    'Oleiros': 'Castelo Branco', 'Olhão': 'Faro', 'Oliveira de Azeméis': 'Aveiro',
    'Oliveira de Frades': 'Viseu', 'Oliveira do Bairro': 'Aveiro',
    'Oliveira do Hospital': 'Coimbra', 'Ourém': 'Santarém', 'Ourique': 'Beja',
    'Ovar': 'Aveiro', 'Paços de Ferreira': 'Porto', 'Palmela': 'Setúbal',
    'Pampilhosa da Serra': 'Coimbra', 'Paredes': 'Porto',
    'Paredes de Coura': 'Viana do Castelo', 'Pedrógão Grande': 'Leiria',
    'Penacova': 'Coimbra', 'Penafiel': 'Porto', 'Penalva do Castelo': 'Viseu',
    'Penamacor': 'Castelo Branco', 'Penedono': 'Viseu', 'Penela': 'Coimbra',
    'Peniche': 'Leiria', 'Peso da Régua': 'Vila Real', 'Pinhel': 'Guarda',
    'Pombal': 'Leiria', 'Ponte da Barca': 'Viana do Castelo',
    'Ponte de Lima': 'Viana do Castelo', 'Ponte de Sor': 'Portalegre',
    'Portalegre': 'Portalegre', 'Portel': 'Évora', 'Portimão': 'Faro',
    'Porto': 'Porto', 'Porto de Mós': 'Leiria', 'Póvoa de Lanhoso': 'Braga',
    'Póvoa de Varzim': 'Porto', 'Proença-a-Nova': 'Castelo Branco',
    'Redondo': 'Évora', 'Reguengos de Monsaraz': 'Évora', 'Resende': 'Viseu',
    'Ribeira de Pena': 'Vila Real', 'Rio Maior': 'Santarém',
    'Sabrosa': 'Vila Real', 'Sabugal': 'Guarda', 'Salvaterra de Magos': 'Santarém',
    'Santa Comba Dão': 'Viseu', 'Santa Maria da Feira': 'Aveiro',
    'Santa Marta de Penaguião': 'Vila Real', 'Santarém': 'Santarém',
    'Santiago do Cacém': 'Setúbal', 'Santo Tirso': 'Porto',
    'São Brás de Alportel': 'Faro', 'São João da Madeira': 'Aveiro',
    'São João da Pesqueira': 'Viseu', 'São Pedro do Sul': 'Viseu',
    'Sardoal': 'Santarém', 'Sátão': 'Viseu', 'Seia': 'Guarda',
    'Seixal': 'Setúbal', 'Sernancelhe': 'Viseu', 'Serpa': 'Beja',
    'Sertã': 'Castelo Branco', 'Sesimbra': 'Setúbal', 'Setúbal': 'Setúbal',
    'Sever do Vouga': 'Aveiro', 'Silves': 'Faro', 'Sines': 'Setúbal',
    'Sintra': 'Lisboa', 'Sobral de Monte Agraço': 'Lisboa', 'Soure': 'Coimbra',
    'Sousel': 'Portalegre', 'Tábua': 'Coimbra', 'Tabuaço': 'Viseu',
    'Tarouca': 'Viseu', 'Tavira': 'Faro', 'Terras de Bouro': 'Braga',
    'Tomar': 'Santarém', 'Tondela': 'Viseu', 'Torre de Moncorvo': 'Bragança',
    'Torres Novas': 'Santarém', 'Torres Vedras': 'Lisboa', 'Trancoso': 'Guarda',
    'Trofa': 'Porto', 'Vagos': 'Aveiro', 'Vale de Cambra': 'Aveiro',
    'Valença': 'Viana do Castelo', 'Valongo': 'Porto', 'Valpaços': 'Vila Real',
    'Vendas Novas': 'Évora', 'Viana do Alentejo': 'Évora',
    'Viana do Castelo': 'Viana do Castelo', 'Vidigueira': 'Beja',
    'Vieira do Minho': 'Braga', 'Vila de Rei': 'Castelo Branco',
    'Vila do Bispo': 'Faro', 'Vila do Conde': 'Porto', 'Vila Flor': 'Bragança',
    'Vila Franca de Xira': 'Lisboa', 'Vila Nova da Barquinha': 'Santarém',
    'Vila Nova de Cerveira': 'Viana do Castelo', 'Vila Nova de Famalicão': 'Braga',
    'Vila Nova de Foz Côa': 'Guarda', 'Vila Nova de Gaia': 'Porto',
    'Vila Nova de Paiva': 'Viseu', 'Vila Nova de Poiares': 'Coimbra',
    'Vila Pouca de Aguiar': 'Vila Real', 'Vila Real': 'Vila Real',
    'Vila Real de Santo António': 'Faro', 'Vila Velha de Ródão': 'Castelo Branco',
    'Vila Verde': 'Braga', 'Vila Viçosa': 'Évora', 'Vimioso': 'Bragança',
    'Vinhais': 'Bragança', 'Viseu': 'Viseu', 'Vizela': 'Braga', 'Vouzela': 'Viseu',
}

# Specific concelho fixes by ID (wrong island names from scraping artefacts)
CONCELHO_FIXES = {
    31381: 'Amarante',
    39189: 'Gondomar',
    31308: 'Cantanhede',
    31547: 'Sousel',
    2817: 'Figueira da Foz',
    2818: 'Figueira da Foz',
    35020: 'Figueira da Foz',
    30629: 'Pombal',
    30632: 'Pombal',
    32605: 'Torres Vedras',
}

with open(INPUT, encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
    fieldnames = rows[0].keys()

distrito_fixed = 0
concelho_fixed = 0

for row in rows:
    row_id = int(row['id'])
    concelho = row['concelho']

    # Fix concelho first (island artefacts)
    if row_id in CONCELHO_FIXES and row['concelho'] != CONCELHO_FIXES[row_id]:
        row['concelho'] = CONCELHO_FIXES[row_id]
        concelho = row['concelho']
        concelho_fixed += 1

    # Fix Ponta Delgada (Lisboa) → Lisboa
    if concelho == 'Ponta Delgada' and row['distrito'] == 'Lisboa':
        row['concelho'] = 'Lisboa'
        concelho = 'Lisboa'
        concelho_fixed += 1

    # Fix Santa Cruz da Graciosa (Faro) → Lagos
    if concelho == 'Santa Cruz da Graciosa' and row['distrito'] == 'Faro':
        row['concelho'] = 'Lagos'
        concelho = 'Lagos'
        concelho_fixed += 1

    # Fix distrito via canonical mapping
    if concelho in CANONICAL and row['distrito'] != CANONICAL[concelho]:
        row['distrito'] = CANONICAL[concelho]
        distrito_fixed += 1

with open(OUTPUT, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. {distrito_fixed} distrito fixes, {concelho_fixed} concelho fixes.")
