import json
import os
import time
import uuid
from typing import List, Optional

import redis
import fakeredis
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from backend import suggestions
except ImportError:
    import suggestions

# ------------------------------------------------------------------------------
# Configuración & Inicialización
# ------------------------------------------------------------------------------
app = FastAPI(
    title="SuperList API - DevOps TP1",
    description="API Backend en Python (FastAPI) para gestionar lista de compras y almacenar datos en Redis.",
    version="1.0.0"
)

# Configuración de CORS para permitir peticiones desde la App Web (Frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def identify_api_node(request, call_next):
    response = await call_next(request)
    response.headers["X-API-Node"] = os.getenv("HOSTNAME", "local")
    return response


# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", None)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_KEY_ITEMS = "superlist:items"

# Instancia global de Redis (con soporte para fallback en memoria si no hay Redis levantado)
_redis_client = None
_redis_mode = "unknown"

def get_redis_client():
    """
    Retorna la instancia de cliente de Redis.
    1. Si REDIS_URL o REDIS_HOST están definidos, intenta conectarse al servidor Redis real.
    2. Si no hay un servidor Redis activo, utiliza una instancia de Redis en memoria (fakeredis)
       para permitir pruebas locales inmediatas sin Docker.
    """
    global _redis_client, _redis_mode

    if _redis_client is not None:
        return _redis_client

    # Intentar conexión a Redis real
    try:
        if REDIS_URL:
            real_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2
            )
            real_client.ping()
            _redis_client = real_client
            host_info = REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL
            _redis_mode = f"Servidor Redis ({host_info})"
        else:
            real_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=1
            )
            real_client.ping()
            _redis_client = real_client
            _redis_mode = f"Servidor Redis ({REDIS_HOST}:{REDIS_PORT})"
            
        print(f"[*] Conectado exitosamente a {_redis_mode}")
        return _redis_client
    except Exception:
        # Fallback a Redis en memoria
        _redis_client = fakeredis.FakeRedis(decode_responses=True)
        _redis_mode = "Redis en memoria (fakeredis - sin Docker)"
        print(f"[*] Servidor Redis externo no detectado en {REDIS_HOST}:{REDIS_PORT}.")
        print(f"[*] Iniciando {_redis_mode} para pruebas locales instantáneas.")
        return _redis_client

# ------------------------------------------------------------------------------
# Modelos de Datos (Pydantic)
# ------------------------------------------------------------------------------
class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, example="Leche Deslactosada")
    category: str = Field(default="otros", example="lacteos")
    quantity: str = Field(default="1 un", max_length=30, example="2 litros")
    note: Optional[str] = Field(default="", max_length=150, example="Marca La Serenísima")

class ItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = None
    quantity: Optional[str] = None
    note: Optional[str] = None
    completed: Optional[bool] = None

class Item(BaseModel):
    id: str
    name: str
    category: str
    quantity: str
    note: str
    completed: bool
    createdAt: int

# ------------------------------------------------------------------------------
# Endpoints de la API
# ------------------------------------------------------------------------------

@app.get("/api/health", summary="Verificar estado de la API y conexión a Redis")
def health_check():
    """Comprueba si el backend está activo y el estado del motor Redis."""
    r = get_redis_client()
    try:
        is_alive = r.ping()
        return {
            "status": "online",
            "version": os.getenv("APP_VERSION", "local"),
            "redis_connected": is_alive,
            "redis_mode": _redis_mode,
            "message": "SuperList API operando correctamente con Redis."
        }
    except Exception as e:
        return {
            "status": "error",
            "redis_connected": False,
            "error": str(e)
        }

@app.get("/api/items", response_model=List[Item], summary="Obtener todos los productos desde Redis")
def get_all_items():
    """Recupera la lista de compras almacenada en el Hash de Redis."""
    r = get_redis_client()
    raw_items = r.hgetall(REDIS_KEY_ITEMS)
    
    items_list = []
    for _, json_val in raw_items.items():
        try:
            item_data = json.loads(json_val)
            items_list.append(item_data)
        except json.JSONDecodeError:
            continue

    # Ordenar por fecha de creación descendente (más nuevos primero)
    items_list.sort(key=lambda x: x.get("createdAt", 0), reverse=True)
    return items_list

@app.post("/api/items", response_model=Item, status_code=status.HTTP_201_CREATED, summary="Agregar un nuevo producto a Redis")
def create_item(item_in: ItemCreate):
    """Crea un nuevo producto y lo almacena en caché en Redis."""
    r = get_redis_client()
    item_id = f"item-{int(time.time() * 1000)}-{uuid.uuid4().hex[:5]}"
    
    new_item = {
        "id": item_id,
        "name": item_in.name.strip(),
        "category": item_in.category,
        "quantity": item_in.quantity.strip() if item_in.quantity else "1 un",
        "note": item_in.note.strip() if item_in.note else "",
        "completed": False,
        "createdAt": int(time.time() * 1000)
    }

    # Guardar en Redis usando HSET (clave de hash: superlist:items)
    r.hset(REDIS_KEY_ITEMS, item_id, json.dumps(new_item))
    return new_item

@app.put("/api/items/{item_id}", response_model=Item, summary="Actualizar producto en Redis (ej. marcar como comprado)")
def update_item(item_id: str, item_update: ItemUpdate):
    """Modifica los atributos de un producto existente en Redis."""
    r = get_redis_client()
    raw_item = r.hget(REDIS_KEY_ITEMS, item_id)
    
    if not raw_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con id '{item_id}' no encontrado en Redis"
        )

    current_data = json.loads(raw_item)

    # Actualizar campos modificados
    if item_update.name is not None:
        current_data["name"] = item_update.name.strip()
    if item_update.category is not None:
        current_data["category"] = item_update.category
    if item_update.quantity is not None:
        current_data["quantity"] = item_update.quantity.strip()
    if item_update.note is not None:
        current_data["note"] = item_update.note.strip()
    if item_update.completed is not None:
        current_data["completed"] = item_update.completed

    # Guardar el producto actualizado en Redis
    r.hset(REDIS_KEY_ITEMS, item_id, json.dumps(current_data))
    return current_data

@app.delete("/api/items/{item_id}", summary="Eliminar un producto de Redis")
def delete_item(item_id: str):
    """Elimina un producto del Hash en Redis."""
    r = get_redis_client()
    deleted_count = r.hdel(REDIS_KEY_ITEMS, item_id)
    
    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto '{item_id}' no encontrado en Redis"
        )

    return {"message": f"Producto '{item_id}' eliminado exitosamente de Redis"}

@app.delete("/api/items/completed/clear", summary="Eliminar todos los productos comprados de Redis")
def clear_completed_items():
    """Busca todos los productos con completed=True y los remueve de Redis."""
    r = get_redis_client()
    raw_items = r.hgetall(REDIS_KEY_ITEMS)
    
    removed_ids = []
    for item_id, json_val in raw_items.items():
        try:
            data = json.loads(json_val)
            if data.get("completed") is True:
                r.hdel(REDIS_KEY_ITEMS, item_id)
                removed_ids.append(item_id)
        except json.JSONDecodeError:
            continue

    return {
        "message": f"Se eliminaron {len(removed_ids)} productos completados de Redis",
        "removed_ids": removed_ids
    }

@app.get("/api/suggestions", summary="Recomendaciones inteligentes de compra (Monolito vs Microservicio)")
def get_suggestions_endpoint(force_mode: Optional[str] = None):
    """
    Retorna recomendaciones analizando la lista de productos actual.
    Soporta ejecución en Monolito Modular (en memoria) o Microservicio (:8001).
    Demuestra latencia, desacoplamiento y degradación elegante ante caídas.
    """
    items = get_all_items()
    service_url = os.getenv("SUGGESTIONS_SERVICE_URL", None)
    return suggestions.get_suggestions(items, service_url=service_url, force_mode=force_mode)

@app.get("/api/redis/stats", summary="Visualizar variables y estado interno de Redis")
def get_redis_stats():
    """Retorna información detallada de las claves, tipos, valores y memoria en Redis."""
    r = get_redis_client()
    try:
        keys = list(r.keys("*"))
        keys_info = []
        for k in keys:
            k_type = r.type(k)
            key_data = {
                "key": k,
                "type": k_type,
            }
            if k_type == "hash":
                raw_hash = r.hgetall(k)
                key_data["field_count"] = len(raw_hash)
                parsed_hash = {}
                for field, val in raw_hash.items():
                    try:
                        parsed_hash[field] = json.loads(val)
                    except Exception:
                        parsed_hash[field] = val
                key_data["data"] = parsed_hash
            elif k_type == "string":
                key_data["data"] = r.get(k)
            keys_info.append(key_data)

        info_dict = {}
        try:
            raw_info = r.info()
            info_dict = {
                "redis_version": str(raw_info.get("redis_version", "N/A")),
                "used_memory_human": str(raw_info.get("used_memory_human", "N/A")),
                "connected_clients": int(raw_info.get("connected_clients", 1)),
                "uptime_in_seconds": int(raw_info.get("uptime_in_seconds", 0)),
            }
        except Exception:
            info_dict = {
                "redis_version": "fakeredis (en memoria)",
                "used_memory_human": "En memoria",
                "connected_clients": 1,
                "uptime_in_seconds": 0,
            }

        return {
            "status": "ok",
            "redis_mode": _redis_mode,
            "total_keys": len(keys),
            "keys": keys_info,
            "info": info_dict
        }
    except Exception as e:
        return {
            "status": "error",
            "redis_mode": _redis_mode,
            "error": str(e),
            "keys": []
        }

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=True)

