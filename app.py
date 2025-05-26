import unicodedata
import re
from bs4 import BeautifulSoup
import time
import requests
import difflib
from math import exp
import httpx
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
cache = None
last_update = 0

def normalizar_nombre_equipo(nombre):
    nombre = nombre.lower()
    nombre = unicodedata.normalize('NFKD', nombre)
    nombre = ''.join(c for c in nombre if not unicodedata.combining(c))  # quita tildes
    nombre = re.sub(r'[^\w\s]', '', nombre)  # elimina símbolos
    nombre = re.sub(r'\s+', ' ', nombre).strip()

    # Casos especiales conocidos
    if "barcelona" in nombre and "espanyol" in nombre:
        return "espanyol"
    if "barcelona" in nombre:
        return "barcelona"
    if "atletico" in nombre and "madrid" in nombre:
        return "atletico madrid"
    if "real madrid" in nombre:
        return "real madrid"
    if "real sociedad" in nombre:
        return "real sociedad"
    if "rayo vallecano" in nombre:
        return "rayo vallecano"
    if "las palmas" in nombre:
        return "las palmas"
    if "real betis" in nombre:
        return "betis"
    if "deportivo alaves" in nombre or "alaves" in nombre:
        return "alaves"

    # General cleanup
    nombre = re.sub(r'\b(cf|fc|club|rcd|ud|cd|s\.a\.d\.|real|atletico|de|balompie)\b', '', nombre)
    return nombre.strip()


def calcular_probabilidades(score_local, score_visit):
    score_local_ajustado = score_local * 1.07
    total = score_local_ajustado + score_visit
    diff = abs(score_local_ajustado - score_visit) / total if total > 0 else 0
    base_empate = 5
    prob_empate = 30 * exp(-base_empate * diff)
    resto_prob = 100 - prob_empate
    if score_local_ajustado > score_visit:
        prob_victoria_local = resto_prob * (0.5 + diff/2)
        prob_victoria_visit = resto_prob - prob_victoria_local
    else:
        prob_victoria_visit = resto_prob * (0.5 + diff/2)
        prob_victoria_local = resto_prob - prob_victoria_visit
    prob_victoria_local = max(0, min(100, prob_victoria_local))
    prob_victoria_visit = max(0, min(100, prob_victoria_visit))
    prob_empate = max(0, min(100, prob_empate))
    total_prob = prob_victoria_local + prob_victoria_visit + prob_empate
    if total_prob > 0:
        prob_victoria_local = round(prob_victoria_local * 100 / total_prob, 1)
        prob_victoria_visit = round(prob_victoria_visit * 100 / total_prob, 1)
        prob_empate = round(prob_empate * 100 / total_prob, 1)
    return prob_victoria_local, prob_victoria_visit, prob_empate

def obtener_estadisticas_avanzadas():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/"
    }

    proxy_url = f"http://api.scraperapi.com?api_key=ad218ecf00d9b705804e71cf6588ab8a&url=https://fbref.com/en/comps/12/La-Liga-Stats"

    response = requests.get(proxy_url, headers=headers)
    soup = BeautifulSoup(response.content, "html.parser")

    def parse_table(table_id, columns):
        table = soup.find("table", id=table_id)
        if not table:
            print(f"❌ No se encontró la tabla: {table_id}")
            return {}
        data = {}
        for row in table.tbody.find_all("tr"):
            if row.get("class") == ["thead"]:
                continue
            team = row.find("th").text.strip()
            stats = {}
            for cell in row.find_all("td"):
                stat = cell.get("data-stat")
                if stat in columns:
                    stats[stat] = cell.text.strip()
            data[team] = stats
        return data

    standard = parse_table("stats_squads_standard_for", ["possession", "goals", "xg", "xg_assist", "npxg", "cards_yellow", "cards_red"])
    passing = parse_table("stats_squads_passing_for", ["passes_completed"])
    misc = parse_table("stats_squads_possession_for", ["touches"])
    shooting = parse_table("stats_squads_shooting_for", ["shots_on_target"])
    keepers_adv = parse_table("stats_squads_keeper_adv_for", ["gk_psxg"])
    keepers = parse_table("stats_squads_keeper_for", ["gk_goals_against", "gk_clean_sheets_pct"])

    equipos = {}
    for team in standard:
        equipos[team] = {
            "team": team,
            "possession": standard[team].get("possession", "0"),
            "goals": standard[team].get("goals", "0"),
            "xg": standard[team].get("xg", "0"),
            "xag": standard[team].get("xg_assist", "0"),
            "npxg": standard[team].get("npxg", "0"),
            "yellow_cards": standard[team].get("cards_yellow", "0"),
            "red_cards": standard[team].get("cards_red", "0"),
            "passes_completed": passing.get(team, {}).get("passes_completed", "0"),
            "touches": misc.get(team, {}).get("touches", "0"),
            "shots_on_target": shooting.get(team, {}).get("shots_on_target", "0"),
            "gk_psxg": keepers_adv.get(team, {}).get("gk_psxg", "0"),
            "gk_goals_against": keepers.get(team, {}).get("gk_goals_against", "0"),
            "gk_clean_sheets_pct": keepers.get(team, {}).get("gk_clean_sheets_pct", "0"),
        }

    return list(equipos.values())

def parse_percent(val):
    return float(val.replace('%', '')) if '%' in val else float(val)

def parse_number(val):
    try:
        return float(val.replace(',', ''))
    except:
        return 0.0

def obtener_partidos():
    API_KEY = '8f766e7e5acb40b78ab66e96222e7755'
    LALIGA_COMPETITION_ID = 2014
    url = f'https://api.football-data.org/v4/competitions/{LALIGA_COMPETITION_ID}/matches?status=SCHEDULED'
    headers = {'X-Auth-Token': API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("Error al consultar la API:", response.status_code, response.text)
        return []
    return response.json().get('matches', [])

def buscar_equipo(nombre, equipos_dict):
    nombre_norm = normalizar_nombre_equipo(nombre)
    for equipo_original, stats in equipos_dict.items():
        if normalizar_nombre_equipo(equipo_original) == nombre_norm:
            return stats

    lista_normalizados = list(equipos_dict.keys())
    coincidencias = difflib.get_close_matches(nombre_norm, [normalizar_nombre_equipo(e) for e in lista_normalizados], n=1, cutoff=0.5)

    if coincidencias:
        for e_original in lista_normalizados:
            if normalizar_nombre_equipo(e_original) == coincidencias[0]:
                return equipos_dict[e_original]

    print(f"⚠️ No se pudo emparejar: {nombre}")
    return None

def calcular_score(team):
    score = 0
    score += parse_number(team['npxg']) * 0.25
    score += parse_number(team['xag']) * 0.15
    score += parse_number(team['shots_on_target']) * 0.10
    score += parse_number(team['goals']) * 0.10
    score += parse_number(team['xg']) * 0.05
    score += parse_percent(team['possession']) * 0.20
    score += parse_number(team['passes_completed']) / 1000 * 0.10
    score += parse_number(team['touches']) / 1000 * 0.05
    score -= parse_number(team.get('gk_psxg', '0')) * 0.20 
    score -= parse_number(team.get('gk_goals_against', '0')) * 0.30
    score += parse_percent(team.get('gk_clean_sheets_pct', '0')) * 0.20
    score -= parse_number(team['yellow_cards']) * 0.05
    score -= parse_number(team['red_cards']) * 0.05
    score += 100
    return score

@app.route("/predicciones")
def predicciones():
    global cache, last_update
    now = time.time()

    if cache and now - last_update < 3600:
        return jsonify(cache)

    stats = obtener_estadisticas_avanzadas()
    partidos = obtener_partidos()
    resultados = []

    if stats and partidos:
        equipos_dict = {normalizar_nombre_equipo(team['team']): team for team in stats}
        for match in partidos:
            home = match['homeTeam']['name']
            away = match['awayTeam']['name']
            fecha = match['utcDate']

            equipo_local = buscar_equipo(home, equipos_dict)
            equipo_visitante = buscar_equipo(away, equipos_dict)

            if not equipo_local or not equipo_visitante:
                continue

            try:
                score_local = calcular_score(equipo_local)
                score_visit = calcular_score(equipo_visitante)
                prob_local, prob_visit, prob_empate = calcular_probabilidades(score_local, score_visit)
                ventaja = abs(score_local - score_visit) / max(score_local, score_visit) * 100

                prediccion = "Empate"
                if prob_local > max(prob_visit, prob_empate):
                    prediccion = home
                elif prob_visit > max(prob_local, prob_empate):
                    prediccion = away

                resultados.append({
                    "date": fecha,
                    "home": home,
                    "away": away,
                    "scoreHome": round(score_local, 2),
                    "scoreAway": round(score_visit, 2),
                    "prediction": prediccion,
                    "probabilities": {
                        "homeWin": prob_local,
                        "awayWin": prob_visit,
                        "draw": prob_empate
                    },
                    "confidence": round(ventaja, 1)
                })
            except Exception as e:
                print(f"Error procesando partido {home} vs {away}: {e}")
                continue

    cache = resultados
    last_update = now
    return jsonify(resultados)

if __name__ == "__main__":
    app.run(debug=True)
