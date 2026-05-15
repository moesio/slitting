import re
import csv
from pathlib import Path

# Diretório raiz
ROOT_DIR = "./output"

# CSV de saída
OUTPUT_CSV = "gurobi_summary.csv"

# Regex
MODEL_REGEX = re.compile(
    r"Optimize a model with\s+(\d+)\s+rows,\s+(\d+)\s+columns",
    re.IGNORECASE
)

GAP_REGEX = re.compile(
    r"gap\s+([0-9.]+)%",
    re.IGNORECASE
)

BEST_BOUND_REGEX = re.compile(
    r"Best objective .* gap ([0-9.]+)%",
    re.IGNORECASE
)

results = []

# Procura todos os gurobi.log
for log_file in sorted(
        Path(ROOT_DIR).rglob("gurobi.log"),
        key=lambda p: (p.parts[-3], p.parts[-2])
):
    rows = None
    cols = None
    gap = None

    try:

        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Constraints e variáveis
        model_match = MODEL_REGEX.search(content)

        if model_match:
            rows = int(model_match.group(1))
            cols = int(model_match.group(2))

        # Gap final
        gaps = GAP_REGEX.findall(content)

        if gaps:
            gap = float(gaps[-1])

        # Fallback
        if gap is None:
            best_bound_match = BEST_BOUND_REGEX.search(content)

            if best_bound_match:
                gap = float(best_bound_match.group(1))

        # -----------------------------
        # Extração do path
        # Exemplo:
        # output/bf_sae1006_050/period_3/gurobi.log
        # -----------------------------

        parts = log_file.parts

        instancia = None
        periodo = None

        if len(parts) >= 3:
            instancia = parts[-3]
            periodo = parts[-2]

        results.append({
            "instancia": instancia,
            "periodo": periodo,
            "constraints": rows,
            "variables": cols,
            "gap_percent": gap,
            "file": str(log_file)
        })

    except Exception as e:
        print(f"Erro ao processar {log_file}: {e}")

# Escreve CSV
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(
        csvfile,
        fieldnames=[
            "instancia",
            "periodo",
            "constraints",
            "variables",
            "gap_percent",
            "file"
        ]
    )

    writer.writeheader()
    writer.writerows(results)

print(f"CSV gerado: {OUTPUT_CSV}")
