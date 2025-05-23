from bs4 import BeautifulSoup
import time
import re
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

def calcular_probabilidades(score_local, score_visit):
    # Añadimos un factor de localía (10% de ventaja para el equipo local)
    score_local_ajustado = score_local * 1.07
    
    # Calculamos la diferencia relativa
    total = score_local_ajustado + score_visit
    diff = abs(score_local_ajustado - score_visit) / total if total > 0 else 0
    
    # Base para el cálculo del empate (ajustable)
    base_empate = 5  # Más alto = menos probabilidad de empate
    
    # Probabilidad de empate (inversamente proporcional a la diferencia)
    prob_empate = 30 * exp(-base_empate * diff)  # Máximo 30% de probabilidad de empate
    
    # Distribuimos el resto entre victoria local y visitante
    resto_prob = 100 - prob_empate
    
    if score_local_ajustado > score_visit:
        prob_victoria_local = resto_prob * (0.5 + diff/2)
        prob_victoria_visit = resto_prob - prob_victoria_local
    else:
        prob_victoria_visit = resto_prob * (0.5 + diff/2)
        prob_victoria_local = resto_prob - prob_victoria_visit
    
    # Aseguramos que no haya valores negativos o mayores a 100
    prob_victoria_local = max(0, min(100, prob_victoria_local))
    prob_victoria_visit = max(0, min(100, prob_victoria_visit))
    prob_empate = max(0, min(100, prob_empate))
    
    # Normalizamos para que sumen exactamente 100%
    total_prob = prob_victoria_local + prob_victoria_visit + prob_empate
    if total_prob > 0:
        prob_victoria_local = round(prob_victoria_local * 100 / total_prob, 1)
        prob_victoria_visit = round(prob_victoria_visit * 100 / total_prob, 1)
        prob_empate = round(prob_empate * 100 / total_prob, 1)
    
    return prob_victoria_local, prob_victoria_visit, prob_empate

def obtener_estadisticas_avanzadas():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "es-ES,es;q=0.9",
    }
    url = "https://fbref.com/en/comps/12/La-Liga-Stats"
    response = httpx.get(url, headers=headers)

    if response.status_code != 200:
        print("❌ Error al acceder a FBref:", response.status_code)
        return []

    soup = BeautifulSoup(response.content, "html.parser")

    table = soup.find("table", id="stats_squads_standard_for")
    if not table:
        print("❌ No se encontró la tabla de estadísticas.")
        return []

    stats = []
    for row in table.tbody.find_all("tr"):
        if row.get("class") == ["thead"]:
            continue
        team_name = row.find("th").text.strip()
        cells = row.find_all("td")
        if len(cells) < 20:
            continue
        possession = cells[12].text.strip()
        touches = cells[13].text.strip()
        passes_completed = cells[16].text.strip()
        shots_on_target = cells[9].text.strip()
        goals = cells[4].text.strip()
        xg = cells[17].text.strip()
        xag = cells[18].text.strip()
        npxg = cells[19].text.strip()
        yellow_cards = cells[10].text.strip()
        red_cards = cells[11].text.strip()

        stats.append({
            "team": team_name,
            "possession": possession,
            "touches": touches,
            "passes_completed": passes_completed,
            "shots_on_target": shots_on_target,
            "goals": goals,
            "xg": xg,
            "xag": xag,
            "npxg": npxg,
            "yellow_cards": yellow_cards,
            "red_cards": red_cards
        })
    return stats

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

    data = response.json()
    return data.get('matches', [])

def buscar_equipo(nombre, equipos_dict):
    nombre = nombre.lower()
    coincidencias = difflib.get_close_matches(nombre, equipos_dict.keys(), n=1, cutoff=0.5)
    if coincidencias:
        return equipos_dict[coincidencias[0]]
    return None

def calcular_score(team):
    score = 0
    # Producción ofensiva (55%)
    score += parse_number(team['npxg']) * 0.20
    score += parse_number(team['xag']) * 0.15
    score += parse_number(team['shots_on_target']) * 0.10
    score += parse_number(team['goals']) * 0.10
    # Construcción de juego (35%)
    score += parse_percent(team['possession']) * 0.10
    score += parse_number(team['passes_completed']) * 0.10
    score += parse_number(team['touches']) * 0.05
    # Penalización por disciplina (10%)
    score -= parse_number(team['yellow_cards']) * 0.05
    score -= parse_number(team['red_cards']) * 0.05
    return score

@app.route("/predicciones")
def predicciones():
    global cache, last_update
    now = time.time()

    if cache and now - last_update < 3600:  # 1 hora de cache
        return jsonify(cache)

    stats = obtener_estadisticas_avanzadas()
    partidos = obtener_partidos()
    resultados = []

    if stats and partidos:
        equipos_dict = {team['team'].lower(): team for team in stats}
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
                
                # Calculamos las probabilidades mejoradas
                prob_local, prob_visit, prob_empate = calcular_probabilidades(score_local, score_visit)
                
                # Determinamos la predicción más probable
                prediccion = "Empate"
                if prob_local > prob_visit and prob_local > prob_empate:
                    prediccion = home
                elif prob_visit > prob_local and prob_visit > prob_empate:
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
                    "confidence": max(prob_local, prob_visit, prob_empate)
                })
            except Exception as e:
                print(f"Error procesando partido {home} vs {away}: {str(e)}")
                continue

    cache = resultados
    last_update = now
    return jsonify(resultados)

if __name__ == "__main__":
    app.run(debug=True)