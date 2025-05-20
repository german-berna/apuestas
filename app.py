from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import re
import requests
import difflib
from math import exp
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def calcular_probabilidad_empate(score_local, score_visit):
    max_valor = max(score_local, score_visit, 1)
    diff_normalizada = abs(score_local - score_visit) / max_valor  # ahora entre 0 y 1

    base = 5  # sensibilidad; más alto = menos empates
    prob = 100 * exp(-base * diff_normalizada)
    return round(prob, 1)


# --- Parte 1: Obtener estadísticas avanzadas de equipos (FBref con Selenium) ---
def obtener_estadisticas_avanzadas():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    url = "https://fbref.com/en/comps/12/La-Liga-Stats"
    driver.get(url)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

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

# --- Parte 2: Obtener próximos partidos ---
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

# --- Parte 3: Emparejamiento más robusto usando similitud ---
def buscar_equipo(nombre, equipos_dict):
    nombre = nombre.lower()
    coincidencias = difflib.get_close_matches(nombre, equipos_dict.keys(), n=1, cutoff=0.5)
    if coincidencias:
        return equipos_dict[coincidencias[0]]
    return None

# --- Parte 4: Cálculo de score avanzado ---
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

# --- Parte 5: Predicción ---
def predecir_partidos(partidos, estadisticas):
    print("\n📊 Predicción avanzada de próximos partidos de LaLiga:\n")
    equipos_dict = {team['team'].lower(): team for team in estadisticas}

    for match in partidos[:10]:
        home = match['homeTeam']['name']
        away = match['awayTeam']['name']
        fecha = match['utcDate']

        equipo_local = buscar_equipo(home, equipos_dict)
        equipo_visitante = buscar_equipo(away, equipos_dict)

        if not equipo_local or not equipo_visitante:
            print(f"{fecha}: {home} vs {away} -> ⚠️ Datos incompletos para predicción")
            continue

        try:
            score_local = calcular_score(equipo_local)
            score_visit = calcular_score(equipo_visitante)
            ventaja = abs(score_local - score_visit) / max(score_local, score_visit) * 100

            print(f"{fecha}: {home} vs {away}")
            print(f" → Score {home}: {round(score_local, 2)}")
            print(f" → Score {away}: {round(score_visit, 2)}")

            if score_local > score_visit:
                print(f" → 🔮 Predicción: gana {home} (ventaja estimada: {ventaja:.1f}%)\n")
            elif score_visit > score_local:
                print(f" → 🔮 Predicción: gana {away} (ventaja estimada: {ventaja:.1f}%)\n")
            else:
                print(" → 🔮 Predicción: empate\n")
        except Exception as e:
            print(f"Error en predicción para {home} vs {away}: {e}\n")


# --- Ejecución principal ---
#if __name__ == "__main__":
#    stats = obtener_estadisticas_avanzadas()
#    partidos = obtener_partidos()
#    if stats and partidos:
#        predecir_partidos(partidos, stats)
#    else:
#        print("No se pudieron obtener todos los datos necesarios.")


from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 🔓 Permite que React acceda a esta API
cache = None
last_update = 0

@app.route("/predicciones")
def predicciones():
    global cache, last_update
    now = time.time()

    if cache and now - last_update < 3600:  # 1 hora de cache
        return jsonify(cache)

    # Si no hay cache o expiró
    stats = obtener_estadisticas_avanzadas()
    partidos = obtener_partidos()
    resultados = []

    if stats and partidos:
        equipos_dict = {team['team'].lower(): team for team in stats}
        for match in partidos[:10]:
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
                ventaja = abs(score_local - score_visit) / max(score_local, score_visit) * 100
                draw_probability = calcular_probabilidad_empate(score_local, score_visit)

                resultados.append({
                    "date": fecha,
                    "home": home,
                    "away": away,
                    "scoreHome": round(score_local, 2),
                    "scoreAway": round(score_visit, 2),
                    "prediction": home if score_local > score_visit else away,
                    "confidence": round(ventaja, 1),
                    "drawProbability": draw_probability
                })
            except:
                continue

    cache = resultados
    last_update = now
    return jsonify(resultados)

if __name__ == "__main__":
    app.run(debug=True)

