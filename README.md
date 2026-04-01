
# 🖥️ jocarsa / monitor

Sistema de monitorización de hardware ligero, basado en Python, que captura métricas del sistema y genera dashboards visuales detallados.

## 📌 Descripción

Este proyecto permite:

* Capturar información completa del sistema (CPU, RAM, disco, red, GPU, temperatura…)
* Almacenar snapshots históricos en SQLite
* Generar dashboards analíticos en imagen (PNG)
* Analizar evolución temporal del rendimiento del sistema

Está pensado para ejecutarse mediante **cron** y construir un histórico continuo de rendimiento.

---

## ⚙️ Arquitectura

El sistema se compone de dos scripts principales:

### 1. Captura de datos

📄 `sistema.py`


* Recoge métricas del sistema usando `psutil`
* Obtiene información adicional:

  * GPU (via `nvidia-smi`)
  * Temperaturas
  * Interfaces de red
  * Usuarios conectados
* Guarda los datos en SQLite (`hardware_status`)

---

### 2. Análisis y visualización

📄 `analitica.py`


* Lee la base de datos histórica
* Calcula:

  * medias, p95, máximos, mínimos
  * tasas de red y disco
  * métricas derivadas
* Genera un dashboard completo en PNG con:

  * CPU, RAM, disco
  * red (RX/TX)
  * IO de disco
  * GPU
  * temperatura
  * uptime y usuarios

---

## 📊 Métricas recogidas

### Sistema

* CPU (% uso, frecuencia, cores, load average)
* RAM y swap
* Disco raíz

### IO

* Lectura/escritura de disco
* Operaciones de disco

### Red

* Bytes enviados/recibidos
* Paquetes
* Errores y drops

### Hardware

* Temperaturas
* GPU (uso, memoria, temperatura, consumo)

### Extra

* Uptime
* Usuarios conectados
* CPU por core

---

## 🗄️ Base de datos

* Motor: SQLite
* Tabla: `hardware_status`
* Estructura creada automáticamente

Ubicación por defecto:

```bash
/home/josevicente/Documentos/hardware_status.sqlite
```

---

## 🚀 Instalación

### Requisitos

```bash
pip install psutil matplotlib
```

Opcional (GPU):

```bash
nvidia-smi
```

---

## ▶️ Uso

### 1. Capturar datos

```bash
python3 sistema.py
```

Recomendado en cron:

```bash
* * * * * /usr/bin/python3 /ruta/sistema.py
```

---

### 2. Generar dashboard

```bash
python3 analitica.py
```

Salida:

```bash
hardware_status_analytics_detailed.png
```

---

## ⚙️ Configuración por variables de entorno

Puedes personalizar rutas:

```bash
export HARDWARE_STATUS_DB=/ruta/db.sqlite
export HARDWARE_STATUS_OUTPUT=/ruta/output.png
export HARDWARE_STATUS_LOG=/ruta/log.log
```

---

## 📈 Dashboard generado

El dashboard incluye varias vistas temporales:

* Últimas 20 horas
* Última semana
* Último mes
* Histórico completo

Cada sección incluye:

* Resumen estadístico
* Gráficas temporales
* Media móvil
* Tasas derivadas (bytes/s, ops/s)

---

## 🧠 Características destacadas

* ✔ Sin dependencias pesadas
* ✔ Base de datos local (SQLite)
* ✔ Resistente a errores (JSON seguro, logs)
* ✔ Compatible con ejecución en cron
* ✔ Preparado para servidores sin interfaz gráfica
* ✔ Escalable a largo plazo (histórico completo)

---

## ⚠️ Consideraciones

* Si no hay GPU, se ignora automáticamente
* Si `nvidia-smi` no está disponible, no falla
* Algunas métricas pueden ser `NULL` dependiendo del sistema
* Requiere permisos de lectura del sistema

---

## 📌 Casos de uso

* Monitorización de servidores
* Análisis de rendimiento a largo plazo
* Diagnóstico de cuellos de botella
* Supervisión de máquinas de entrenamiento IA
* Sistemas sin herramientas externas (tipo Prometheus)

---

## 🧩 Posibles mejoras

* Exportación a JSON / CSV
* API REST
* Interfaz web
* Alertas automáticas (CPU, temperatura…)
* Integración con sistemas externos

---

## 📄 Licencia

MIT (o la que decidas añadir)

---

## 👨‍💻 Autor

**Jose Vicente Carratalá**
Proyecto dentro del ecosistema **JOCARSA**

