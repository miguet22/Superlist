# SuperList

[![CI](https://github.com/miguet22/TPI1_DEVOPS/actions/workflows/ci.yml/badge.svg?branch=actions)](https://github.com/miguet22/TPI1_DEVOPS/actions/workflows/ci.yml?query=branch%3Aactions)
[![Valoración SAST Python](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmiguet22%2FTPI1_DEVOPS%2Fci-badges%2Factions.json)](https://github.com/miguet22/TPI1_DEVOPS/actions/workflows/ci.yml?query=branch%3Aactions)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=miguet22_TPI1_DEVOPS&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=miguet22_TPI1_DEVOPS)

Trabajo Práctico N.º 1 de DevOps — UTN FRRe, 2026.

Este documento está organizado en dos grandes partes para facilitar la defensa y explicación durante el coloquio:
* **[PARTE 1: ARQUITECTURA BASE (Lo que se tenía hasta ahora)](#parte-1-arquitectura-base-lo-que-se-tenía-hasta-ahora):** Aplicación de lista de compras, réplicas, balanceo con Nginx, persistencia en Redis, CI/CD, SAST y despliegue cloud.
* **[PARTE 2: EXTENSIÓN TEMA 1 — MONOLITO MODULAR Y MICROSERVICIOS (Lo nuevo para el Coloquio)](#parte-2-extensión-tema-1--monolito-modular-y-microservicios):** Justificación teórica del "por qué", comparación de arquitectura, costos introducidos, degradación elegante y guión práctico paso a paso de la demo.

---

# PARTE 1: ARQUITECTURA BASE (Lo que se tenía hasta ahora)

SuperList es una lista de compras que integra una aplicación web, una API REST en FastAPI y una base de datos en Redis. Permite agregar productos, marcarlos como comprados, volverlos a dejar pendientes y eliminarlos. La web nunca accede directamente a Redis: todas las operaciones pasan por la API.

## Arquitectura Base

El entorno local original se levanta con Docker Compose con alta disponibilidad y réplicas:

```text
                         ┌─ frontend
Navegador ──> Nginx ─────┼─ frontend2
             :8080       └─ frontend3
                 │
                 │ /api
                 ├───────── backend  ─┐
                 ├───────── backend2 ─┼──> Redis
                 └───────── backend3 ─┘
```

Nginx funciona como proxy reverso y distribuye las solicitudes entre tres instancias de la web y tres de la API. Las API comparten el mismo Redis, por lo que cualquier réplica puede consultar o modificar la lista. Redis está en una red interna y tiene un volumen para conservar los datos cuando se recrean los contenedores.

Solo el proxy publica un puerto en el host. La comunicación queda separada en dos redes:
* `web`: proxy, aplicaciones web y API.
* `data`: API y Redis. Esta red es interna.

## Ejecución Local Base

Se necesita Docker con Docker Compose y el motor iniciado.

```powershell
docker compose up -d --build --wait
```

La aplicación queda disponible en [http://localhost:8080](http://localhost:8080) y la documentación de la API en [http://localhost:8080/docs](http://localhost:8080/docs).

Para consultar el estado de los servicios o detener el entorno:

```powershell
docker compose ps
docker compose down
```

`docker compose down` conserva el volumen de Redis. La opción `-v` también elimina ese volumen y, por lo tanto, los productos guardados.

## Prueba Original de Balanceo y Failover

Una forma corta de comprobar la tolerancia a caídas de réplicas en la arquitectura base:

1. Agregar un producto desde la web, marcarlo como comprado y eliminarlo.
2. Abrir **Visor Redis** para comprobar que la información fue guardada por la API en `superlist:items`.
3. Hacer varias solicitudes y observar `X-Upstream-Addr` y `X-API-Node` en las cabeceras de respuesta.
4. Detener una réplica web y una réplica de API:

   ```powershell
   docker compose stop frontend backend
   ```

5. Repetir las operaciones desde la web. Las otras réplicas continúan respondiendo.
6. Restaurar las instancias detenidas:

   ```powershell
   docker compose start --wait frontend backend
   ```

Las cabeceras también se pueden consultar desde PowerShell con el script existente:

```powershell
powershell -File scripts/demo-failover.ps1
```

## Servicios Base

| Servicio | Tecnología | Cantidad local | Función |
| --- | --- | ---: | --- |
| Proxy | Nginx | 1 | Punto de entrada y balanceo de carga |
| Web | HTML, CSS, JavaScript y Nginx | 3 | Interfaz de la lista y consumo de la API |
| API | FastAPI y Uvicorn | 3 | Reglas de la aplicación y acceso exclusivo a Redis |
| Datos | Redis 7 | 1 | Almacenamiento de productos y estado de compra |

## Endpoints Base de la API

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/api/health` | Estado de la API y conexión con Redis |
| `GET` | `/api/items` | Obtener la lista |
| `POST` | `/api/items` | Agregar un producto |
| `PUT` | `/api/items/{id}` | Editar o cambiar el estado de un producto |
| `DELETE` | `/api/items/{id}` | Eliminar un producto |
| `DELETE` | `/api/items/completed/clear` | Eliminar los productos comprados |
| `GET` | `/api/redis/stats` | Consultar claves, tipos y datos para el visor de Redis |

## Integración Continua y Despliegue en la Nube

El workflow [.github/workflows/ci.yml](.github/workflows/ci.yml) incluye:
* Tests unitarios con `pytest` y `fakeredis`.
* Tests de disponibilidad del frontend con el runner de Node.js.
* Análisis SAST del backend con Bandit (valoración A sin hallazgos).
* Quality Gate de SonarCloud.
* Publicación automatizada de imágenes en Docker Hub (`cazm0/superlist-frontend` y `cazm0/superlist-backend`).
* Despliegue automático en Render con notificación en Discord.

---

# PARTE 2: EXTENSIÓN TEMA 1 — MONOLITO MODULAR Y MICROSERVICIOS

> **Tema Asignado:** Tema 1 — Arquitectura: Monolito modular y microservicios.  
> **Pregunta Guía:** *¿Cuándo conviene separar un módulo como servicio y qué costo introduce?*  
> **Demo Práctica:** *Ejecutar dos módulos juntos y luego separar uno detrás de una API, provocar su caída para observar el impacto.*

---

## 1. El "Por Qué" de Todo (Fundamentación Teórica y Arquitectural)

### A. Definición de los Dos Módulos
Para cumplir con la consigna, la solución descompone el negocio en dos dominios bien delimitados:

1. **Módulo Core (Gestión de Compras):**
   * Responsabilidad: Alta, baja, modificación y estado de compra de los productos en Redis.
   * Requisito: **Crítico**. Si este módulo falla, el usuario no puede usar la aplicación.
2. **Módulo Auxiliar (Recomendaciones e Insights de Canasta):**
   * Responsabilidad: Analiza la canasta actual y genera sugerencias inteligentes de compra complementarias (ej. si hay fideos, sugiere salsa de tomate y queso; si hay café, sugiere azúcar o leche) y consejos de nutrición/variedad.
   * Requisito: **Secundario/No bloqueante**. Si este módulo falla, el usuario **aún debe poder comprar normalmente**.

---

### B. Respuesta a la Pregunta Guía

#### ¿Cuándo conviene separar un módulo como servicio?
Conviene extraer un módulo fuera del monolito hacia su propio microservicio cuando se presentan uno o varios de los siguientes factores:

1. **Escalabilidad Asimétrica:**
   * El cálculo de sugerencias, analítica o IA puede requerir intensivo uso de CPU o memoria en comparación con las operaciones de lectura/escritura de la lista. En un microservicio, podemos escalar a 10 réplicas el servicio de sugerencias sin malgastar recursos en el core.
2. **Aislamiento de Fallos (*Fault Isolation*):**
   * Si el motor de sugerencias experimenta un error crítico, bloqueo o fuga de memoria, **no debe voltear el proceso de la lista de compras**. El core sigue funcionando.
3. **Ciclos de Despliegue y Autonomía de Equipos:**
   * Un equipo especializado en analítica/IA puede modificar, testear y desplegar nuevas reglas o algoritmos de recomendación todos los días sin necesidad de recompilar ni redesplegar la API core.
4. **Heterogeneidad Tecnológica:**
   * Permite que el nuevo servicio utilice librerías o runtimes específicos (ej. Python para machine learning, Go para alta concurrencia) independientemente de la tecnología del core.

#### ¿Qué costos introduce la separación?
Separar un módulo introduce costos técnicos y operativos reales que deben justificarse:

1. **Latencia de Red y Serialización (El costo de la llamada):**
   * En el monolito modular, la llamada es una invocación a una función en memoria (nanosegundos o < 0.1 ms).
   * En el microservicio, la llamada viaja por la red (HTTP/REST o gRPC) requiriendo serialización/deserialización JSON, socket TCP y resolución DNS (2 ms a 15 ms).
2. **Riesgo de Fallas en Cascada (*Cascading Failures*):**
   * En un sistema distribuido, la red es intrínsecamente no confiable. Si el backend core espera sincrónicamente al microservicio sin timeout ni manejo de errores, la caída del microservicio arrastra consigo al backend (HTTP 500 para todo el usuario).
3. **Complejidad de Resiliencia (*Graceful Degradation*):**
   * Obliga a implementar patrones de resiliencia: timeouts estrictos, reintentos y *fallbacks* (degradación elegante) para que la caída parcial sea transparente o tolerada.
4. **Sobrecarga Operativa y DevOps:**
   * Más imágenes Docker a construir y mantener, más puertos, configuración de service discovery, orquestación en `compose.yaml`, monitoreo distribuido y trazas.

---

## 2. Arquitectura de la Extensión

```text
                             ┌─ frontend (x3)
Navegador ──> Nginx (:8080) ─┼─ backend  (x3) ──> Redis (:6379)
                             │      │
                             │      │ (Llamada HTTP REST interna / POST :8001)
                             │      ▼
                             └─ suggestions-service (:8001) [Microservicio Desacoplado]
```

### Los Dos Modos Soportados por el Sistema:

1. **Modo Monolito Modular (`force_mode=monolith` o sin URL externa):**
   * La API resuelve las recomendaciones mediante el módulo interno `backend/suggestions.py` directamente en memoria dentro del mismo proceso.
   * Latencia observada: **< 0.2 ms**.
2. **Modo Microservicio Desacoplado (`SUGGESTIONS_SERVICE_URL=http://suggestions:8001/api/suggestions`):**
   * El servicio independiente corre en el contenedor `suggestions` (puerto 8001).
   * La API core realiza una petición HTTP al microservicio con un **timeout estricto de 1.5s**.
   * Latencia observada: **~2 - 5 ms**.

### Patrón de Resiliencia: Degradación Elegante (*Graceful Degradation*)

Cuando el microservicio de sugerencias se detiene intencionalmente:
* La llamada HTTP falla (conexión rechazada o timeout).
* El backend **NO arroja HTTP 500**. Captura la excepción, marca la respuesta como `"status": "degraded"`, `"degraded": true`, y sirve sugerencias de respaldo en caché local.
* La interfaz web muestra un badge ámbar ⚠️ indicando **Modo Degradado (Falla Parcial Tolerada)**.
* **El usuario puede continuar agregando, marcando y borrando productos sin interrupciones**.

---

## 3. Guía Paso a Paso para la Defensa en el Coloquio

Durante la presentación ante los profesores, podés seguir este guión exacto:

### Paso 1: Levantar el entorno y mostrar ambos módulos activos

1. Iniciar los contenedores:
   ```powershell
   docker compose up -d --build --wait
   ```
2. Abrir el navegador en [http://localhost:8080](http://localhost:8080).
3. **Explicación al docente:**
   * *"Acá vemos la aplicación con sus dos módulos: el módulo Core de la lista y la tarjeta superior de **Sugerencias Inteligentes & Insights**."*
   * *"Observen el badge verde: indica **Microservicio Online (:8001)** y muestra la latencia de red (aprox 2-4 ms), que evidencia el costo de serialización y transporte HTTP entre contenedores."*
   * *"Si hacemos clic en una sugerencia (+ Salsa de Tomate), se agrega inmediatamente a la lista."*

---

### Paso 2: Mostrar el contraste con el Monolito Modular

1. Consultar el endpoint forzando la ejecución en memoria:
   ```powershell
   Invoke-RestMethod "http://localhost:8080/api/suggestions?force_mode=monolith"
   ```
2. **Explicación al docente:**
   * *"Cuando ejecutamos ambos módulos juntos como **Monolito Modular** en el mismo proceso, la latencia cae a menos de 0.2 ms porque no hay salto de red ni serialización. Esta es la gran ventaja del monolito cuando no hay necesidad de escalar componentes por separado."*

---

### Paso 3: Provocar la caída del microservicio y observar el impacto

1. En la terminal, detener el microservicio auxiliar:
   ```powershell
   docker compose stop suggestions
   ```
2. Volver al navegador o recargar la página:
   * La tarjeta de sugerencias cambia automáticamente a badge rojo/ámbar: **Microservicio Degradado ⚠️**.
   * Aparece el banner informativo: *"El microservicio de sugerencias no responde, pero la lista principal sigue 100% operativa."*
3. Agregar o eliminar un producto de la lista (ej. agregar "Arroz"):
   * La operación se completa inmediatamente en Redis con 200 OK.
4. **Explicación al docente (Momento Clave):**
   * *"Aquí estamos demostrando el objetivo central del tema: **Aislamiento de fallos y prevención de fallas en cascada**."*
   * *"Al haber separado el módulo detrás de una API, su caída no provocó un fallo general del sistema. Gracias a la **Degradación Elegante**, el usuario puede seguir comprando sin notar que un servicio secundario está caído."*

---

### Paso 4: Restaurar el microservicio (Self-Healing / Recuperación)

1. Volver a iniciar el microservicio:
   ```powershell
   docker compose start suggestions
   ```
2. En 3 segundos, recargar o esperar el ciclo de sondeo:
   * El badge vuelve a verde: **Microservicio Online (:8001)**.
   * La aplicación se recuperó de forma automática sin haber requerido reiniciar la API core ni el proxy.

---

### Demostración Automatizada en un Solo Comando

Para ejecutar toda la secuencia de forma automatizada por consola y mostrar las métricas en pantalla:

```powershell
powershell -File scripts/demo-microservices.ps1
```

Este script ejecuta automáticamente:
1. Consulta en modo Monolito Modular y muestra latencia en memoria.
2. Consulta en modo Microservicio y muestra latencia HTTP.
3. Ejecuta `docker compose stop suggestions` y comprueba que `/api/items` sigue vivo mientras `/api/suggestions` entra en modo degradado con código 200.
4. Ejecuta `docker compose start suggestions` y confirma la recuperación del servicio.

---

## 4. Matriz Comparativa Resumen

| Criterio | Monolito Modular | Microservicio Desacoplado | Microservicio Caído (Tolerancia) |
| --- | --- | --- | --- |
| **Ubicación de ejecución** | Mismo proceso (`backend`) | Contenedor separado (`suggestions:8001`) | Contenedor apagado |
| **Tipo de llamada** | In-process (función en RAM) | Red interna HTTP REST (`urllib`) | Intento HTTP con Timeout (1.5s) |
| **Latencia promedio** | **~0.1 ms** (Casi nula) | **~3.0 ms** (Costo de red + JSON) | **~15 ms** (Tiempo de fallo controlado) |
| **Impacto de una falla** | Riesgo de arrastrar todo el proceso | Aislado en su propio contenedor | **Degradación Elegante** (Core sigue 200 OK) |
| **Despliegue** | Unificado (todo o nada) | Independiente | N/A |
| **Complejidad DevOps** | Baja (1 solo backend) | Media (Más servicios en Compose) | Requiere Circuit Breaker / Fallback |

---

## 5. Nuevos Archivos del Proyecto

```text
suggestions_service/
  ├── Dockerfile               Imagen Docker del microservicio independiente
  ├── main.py                  FastAPI del microservicio en puerto 8001
  └── requirements.txt         Dependencias específicas del microservicio
backend/
  └── suggestions.py           Módulo de recomendaciones y cliente con degradación elegante
scripts/
  └── demo-microservices.ps1   Script interactivo de PowerShell para el coloquio
```
