"""
Módulo de Sugerencias y Recomendaciones de Compra.
Parte del Monolito Modular y base para el Microservicio desacoplado.
"""
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# Reglas de afinidad de productos para la demo
ASSOCIATION_RULES: Dict[str, List[Dict[str, str]]] = {
    "fideos": [
        {"name": "Salsa de Tomate", "category": "despensa", "quantity": "1 lata", "reason": "Combina con tus fideos"},
        {"name": "Queso Rallado", "category": "lacteos", "quantity": "1 sobre", "reason": "Para espolvorear en tus pastas"}
    ],
    "pasta": [
        {"name": "Salsa de Tomate", "category": "despensa", "quantity": "1 lata", "reason": "Acompañamiento clásico"},
        {"name": "Queso Rallado", "category": "lacteos", "quantity": "1 sobre", "reason": "Para tus pastas"}
    ],
    "leche": [
        {"name": "Café", "category": "despensa", "quantity": "1 frasco", "reason": "Para el desayuno o merienda"},
        {"name": "Galletitas", "category": "snacks", "quantity": "1 paquete", "reason": "Ideal para acompañar tu leche"}
    ],
    "cafe": [
        {"name": "Azúcar", "category": "despensa", "quantity": "1 kg", "reason": "Para endulzar tu café"},
        {"name": "Leche", "category": "lacteos", "quantity": "1 L", "reason": "Para cortar el café"}
    ],
    "pan": [
        {"name": "Manteca", "category": "lacteos", "quantity": "1 paquete", "reason": "Para untar en tus tostadas"},
        {"name": "Mermelada", "category": "despensa", "quantity": "1 frasco", "reason": "Para acompañar tu pan"}
    ],
    "carne": [
        {"name": "Carbón", "category": "otros", "quantity": "1 bolsa", "reason": "Para el asado"},
        {"name": "Lechuga y Tomate", "category": "frutas", "quantity": "1 kg", "reason": "Para armar una ensalada fresca"}
    ],
    "hamburguesas": [
        {"name": "Pan de Hamburguesa", "category": "panaderia", "quantity": "1 paquete", "reason": "Para armar las hamburguesas"},
        {"name": "Queso Cheddar", "category": "lacteos", "quantity": "1 paquete", "reason": "Para derretir sobre la hamburguesa"}
    ],
    "arroz": [
        {"name": "Atún en lata", "category": "despensa", "quantity": "2 latas", "reason": "Proteína rápida para combinar con arroz"},
        {"name": "Aceite de Oliva", "category": "despensa", "quantity": "1 botella", "reason": "Condimento esencial"}
    ]
}

DEFAULT_ESSENTIALS: List[Dict[str, str]] = [
    {"name": "Leche", "category": "lacteos", "quantity": "1 L", "reason": "Básico esencial del hogar"},
    {"name": "Pan", "category": "panaderia", "quantity": "1 bolsa", "reason": "Básico para el desayuno"},
    {"name": "Huevos", "category": "lacteos", "quantity": "1 docena", "reason": "Proteína versátil"},
    {"name": "Frutas de estación", "category": "frutas", "quantity": "1 kg", "reason": "Para una alimentación equilibrada"},
]


def compute_suggestions(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Motor de recomendaciones ejecutado en memoria (Monolito Modular).
    Analiza los productos existentes y genera sugerencias relevantes sin coste de red.
    """
    existing_names = {
        item.get("name", "").lower().strip()
        for item in items
        if isinstance(item, dict) and item.get("name")
    }
    categories_present = {
        item.get("category", "")
        for item in items
        if isinstance(item, dict) and item.get("category")
    }

    suggested: List[Dict[str, str]] = []
    seen_names = set(existing_names)

    # 1. Asociaciones contextuales basadas en lo que ya está en la lista
    for item in items:
        if not isinstance(item, dict):
            continue
        item_name = item.get("name", "").lower()
        for keyword, rules in ASSOCIATION_RULES.items():
            if keyword in item_name:
                for rule in rules:
                    rule_name = rule["name"].lower()
                    if rule_name not in seen_names:
                        suggested.append(rule)
                        seen_names.add(rule_name)

    # 2. Si hay pocas sugerencias, completar con esenciales
    for ess in DEFAULT_ESSENTIALS:
        if len(suggested) >= 4:
            break
        ess_name = ess["name"].lower()
        if ess_name not in seen_names:
            suggested.append(ess)
            seen_names.add(ess_name)

    # 3. Insights sobre la canasta de compras
    total_count = len(items)
    if total_count == 0:
        tip = "¡Tu lista está vacía! Comienza agregando básicos esenciales."
    elif len(categories_present) >= 3:
        tip = f"¡Excelente variedad! Tienes {len(categories_present)} categorías distintas en tu lista."
    elif "lacteos" in categories_present and "panaderia" in categories_present:
        tip = "¡Buen combo para desayunos y meriendas!"
    else:
        tip = f"Tienes {total_count} producto(s) planificados en tu lista de compras."

    return {
        "suggestions": suggested[:4],
        "insights": {
            "item_count": total_count,
            "categories_present": sorted(list(categories_present)),
            "tip": tip
        }
    }


def get_suggestions(
    items: List[Dict[str, Any]],
    service_url: Optional[str] = None,
    force_mode: Optional[str] = None
) -> Dict[str, Any]:
    """
    Punto de entrada de sugerencias.
    Soporta:
    - Modo Monolito Modular: Ejecución directa en memoria (en el mismo proceso).
    - Modo Microservicio: Llamada HTTP REST con degradación elegante (Graceful Degradation) ante fallos.
    """
    start_time = time.perf_counter()

    # Si se fuerza monolito o no hay URL configurada -> Monolito modular (en memoria)
    if force_mode == "monolith" or not service_url:
        result = compute_suggestions(items)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "mode": "monolith",
            "architecture": "Monolito Modular (en memoria)",
            "status": "online",
            "latency_ms": elapsed_ms,
            "service_url": "in-process",
            "degraded": False,
            "suggestions": result["suggestions"],
            "insights": result["insights"]
        }

    if not (service_url.startswith("http://") or service_url.startswith("https://")):
        raise ValueError("Esquema de URL no permitido para microservicio")

    # Modo Microservicio: Llamada por red HTTP REST
    payload = json.dumps({"items": items}).encode("utf-8")
    req = urllib.request.Request(
        service_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "SuperList-Backend"},
        method="POST"
    )

    try:
        # Timeout corto (1.5s) para proteger al backend de demoras del microservicio
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "mode": "microservice",
                "architecture": "Microservicio Desacoplado (:8001)",
                "status": "online",
                "latency_ms": elapsed_ms,
                "service_url": service_url,
                "degraded": False,
                "suggestions": data.get("suggestions", []),
                "insights": data.get("insights", {})
            }
    except Exception as err:
        # DEGRADACIÓN ELEGANTE (Graceful Degradation):
        # La caída del microservicio NO debe tumbar el Core de la aplicación (evita Cascading Failure).
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        fallback = compute_suggestions(items)
        return {
            "mode": "microservice",
            "architecture": "Microservicio Desacoplado (:8001)",
            "status": "degraded",
            "latency_ms": elapsed_ms,
            "service_url": service_url,
            "degraded": True,
            "error_detail": f"Fallo al conectar con el microservicio: {type(err).__name__}",
            "suggestions": fallback["suggestions"],
            "insights": {
                **fallback["insights"],
                "tip": "⚠️ Microservicio fuera de línea. Mostrando sugerencias de respaldo en modo degradado."
            }
        }
