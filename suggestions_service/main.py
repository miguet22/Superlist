import os
import time
from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="SuperList Suggestions Microservice",
    description="Microservicio desacoplado para recomendaciones y análisis de canasta de compras.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SuggestionItem(BaseModel):
    name: str
    category: str
    quantity: str
    reason: str

class InsightsData(BaseModel):
    item_count: int
    categories_present: List[str]
    tip: str

class SuggestionsPayload(BaseModel):
    items: List[Dict[str, Any]] = []

class SuggestionsResponse(BaseModel):
    service: str = "suggestions-service"
    version: str = "1.0.0"
    source: str = "microservice"
    node: str = "local"
    suggestions: List[SuggestionItem]
    insights: InsightsData

# Reglas de afinidad de productos para el motor de microservicio
ASSOCIATION_RULES = {
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

DEFAULT_ESSENTIALS = [
    {"name": "Leche", "category": "lacteos", "quantity": "1 L", "reason": "Básico esencial del hogar"},
    {"name": "Pan", "category": "panaderia", "quantity": "1 bolsa", "reason": "Básico para el desayuno"},
    {"name": "Huevos", "category": "lacteos", "quantity": "1 docena", "reason": "Proteína versátil"},
    {"name": "Frutas de estación", "category": "frutas", "quantity": "1 kg", "reason": "Para una alimentación equilibrada"},
]

@app.get("/health", summary="Health check del microservicio")
def health():
    return {
        "status": "healthy",
        "service": "suggestions-service",
        "hostname": os.getenv("HOSTNAME", "suggestions-node"),
        "timestamp": int(time.time())
    }

@app.post("/api/suggestions", response_model=SuggestionsResponse, summary="Generar sugerencias de compra")
def generate_suggestions(payload: SuggestionsPayload):
    items = payload.items
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

    suggested = []
    seen_names = set(existing_names)

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

    for ess in DEFAULT_ESSENTIALS:
        if len(suggested) >= 4:
            break
        ess_name = ess["name"].lower()
        if ess_name not in seen_names:
            suggested.append(ess)
            seen_names.add(ess_name)

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
        "service": "suggestions-service",
        "version": "1.0.0",
        "source": "microservice",
        "node": os.getenv("HOSTNAME", "suggestions-node"),
        "suggestions": suggested[:4],
        "insights": {
            "item_count": total_count,
            "categories_present": sorted(list(categories_present)),
            "tip": tip
        }
    }
