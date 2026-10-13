param(
    [string]$BaseUrl = 'http://127.0.0.1:8080'
)

$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')

function Write-Step([string]$Title) {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor Cyan
}

try {
    Write-Host ""
    Write-Host "######################################################################" -ForegroundColor Green
    Write-Host " DEMO TEMA 1: MONOLITO MODULAR Y MICROSERVICIOS" -ForegroundColor Green
    Write-Host " Pregunta guia: ¿Cuando conviene separar un modulo como servicio" -ForegroundColor White
    Write-Host "               y que costo introduce?" -ForegroundColor White
    Write-Host "######################################################################" -ForegroundColor Green

    # -------------------------------------------------------------------------
    # FASE 1: Monolito Modular (Llamada interna en memoria)
    # -------------------------------------------------------------------------
    Write-Step "FASE 1: Ejecucion como Monolito Modular (en memoria)"
    Write-Host "Consultando sugerencias forzando modo Monolito (llamada directa en memoria)..." -ForegroundColor Gray
    
    $monoResp = Invoke-RestMethod "$BaseUrl/api/suggestions?force_mode=monolith" -TimeoutSec 10
    Write-Host "-> Modo de arquitectura : $($monoResp.architecture)" -ForegroundColor Green
    Write-Host "-> Estado del servicio  : $($monoResp.status)" -ForegroundColor Green
    Write-Host "-> Latencia medida      : $($monoResp.latency_ms) ms" -ForegroundColor Cyan
    Write-Host "-> Origen de ejecucion  : $($monoResp.service_url)" -ForegroundColor Gray
    Write-Host "-> Items sugeridos      : $($monoResp.suggestions.Count) productos" -ForegroundColor White
    Write-Host ""
    Write-Host "[Analisis DevOps]: En el Monolito Modular, la llamada se ejecuta en el" -ForegroundColor DarkCyan
    Write-Host "mismo espacio de memoria (sin red). Costo de latencia casi nulo, pero" -ForegroundColor DarkCyan
    Write-Host "comparte CPU, memoria y ciclo de despliegue con la API principal." -ForegroundColor DarkCyan

    # -------------------------------------------------------------------------
    # FASE 2: Microservicio Desacoplado (Llamada HTTP a suggestions:8001)
    # -------------------------------------------------------------------------
    Write-Step "FASE 2: Ejecucion como Microservicio Desacoplado (:8001)"
    Write-Host "Consultando sugerencias a traves del Microservicio independiente..." -ForegroundColor Gray
    
    $microResp = Invoke-RestMethod "$BaseUrl/api/suggestions" -TimeoutSec 10
    Write-Host "-> Modo de arquitectura : $($microResp.architecture)" -ForegroundColor Green
    Write-Host "-> Estado del servicio  : $($microResp.status)" -ForegroundColor Green
    Write-Host "-> Latencia medida      : $($microResp.latency_ms) ms" -ForegroundColor Yellow
    Write-Host "-> URL del Microservicio: $($microResp.service_url)" -ForegroundColor Gray
    Write-Host "-> Items sugeridos      : $($microResp.suggestions.Count) productos" -ForegroundColor White
    Write-Host ""
    Write-Host "[Analisis DevOps]: Al separar el modulo en un microservicio, se introduce" -ForegroundColor DarkCyan
    Write-Host "un costo de red y serializacion JSON (latencia de red vs memoria). A cambio," -ForegroundColor DarkCyan
    Write-Host "el modulo puede escalar individualmente y tener su propio ciclo de vida." -ForegroundColor DarkCyan

    # -------------------------------------------------------------------------
    # FASE 3: Provocar la Caida del Microservicio y Observar Impacto
    # -------------------------------------------------------------------------
    Write-Step "FASE 3: Provocar la caida del Microservicio y observar el impacto"
    Write-Host "Deteniendo el contenedor del microservicio: 'docker compose stop suggestions'..." -ForegroundColor Magenta
    
    docker compose stop suggestions
    if ($LASTEXITCODE -ne 0) { throw "No se pudo detener el servicio suggestions." }
    
    Write-Host "Microservicio detenido exitosamente." -ForegroundColor Gray
    Write-Host "Comprobando impacto en el Core de la aplicacion (Lista de compras)..." -ForegroundColor White

    # 1. Comprobar que el Core sigue funcionando al 100%
    $items = Invoke-RestMethod "$BaseUrl/api/items" -TimeoutSec 10
    Write-Host "-> Core de la lista (/api/items) : 200 OK (La lista sigue disponible!)" -ForegroundColor Green

    # 2. Comprobar que el endpoint secundario aplica degradacion elegante
    $degradedResp = Invoke-RestMethod "$BaseUrl/api/suggestions" -TimeoutSec 10
    Write-Host "-> Endpoint de sugerencias       : $($degradedResp.status) (Modo Degradado)" -ForegroundColor Yellow
    Write-Host "-> Degradacion activa            : $($degradedResp.degraded)" -ForegroundColor Yellow
    Write-Host "-> Detalle de la falla tolerada  : $($degradedResp.error_detail)" -ForegroundColor Red
    Write-Host "-> Mensaje para el usuario       : $($degradedResp.insights.tip)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[Analisis DevOps]: Se evito la falla en cascada (Cascading Failure)." -ForegroundColor Green
    Write-Host "A pesar de que el microservicio auxiliar cayo, la API principal y el" -ForegroundColor Green
    Write-Host "frontend continuan operando normalmente gracias a la Degradacion Elegante." -ForegroundColor Green

    # -------------------------------------------------------------------------
    # FASE 4: Restauracion y Recuperacion Automatica
    # -------------------------------------------------------------------------
    Write-Step "FASE 4: Restaurar el Microservicio y verificar recuperacion"
    Write-Host "Iniciando nuevamente el contenedor: 'docker compose start suggestions'..." -ForegroundColor Magenta
    
    docker compose start suggestions
    if ($LASTEXITCODE -ne 0) { throw "No se pudo restaurar el servicio suggestions." }

    Write-Host "Esperando 4 segundos a que el contenedor este listo..." -ForegroundColor Gray
    Start-Sleep -Seconds 4

    $recoveredResp = Invoke-RestMethod "$BaseUrl/api/suggestions" -TimeoutSec 10
    Write-Host "-> Estado tras recuperacion      : $($recoveredResp.status)" -ForegroundColor Green
    Write-Host "-> Modo de arquitectura          : $($recoveredResp.architecture)" -ForegroundColor Green
    Write-Host "-> Latencia restaurada           : $($recoveredResp.latency_ms) ms" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host " DEMO FINALIZADA CON EXITO: Resiliencia y Desacoplamiento Comprobados" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
}
finally {
    Pop-Location
}
