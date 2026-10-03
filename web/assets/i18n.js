// Dashboard translations, keyed by the English text so the markup stays plain
// English. Text set later by app.js is translated as it appears when it
// matches a key exactly; messages with numbers in them stay in English.
// To add a language: copy the `es` block, translate the values, add it to
// DICTIONARIES and add an <option> to #ui-lang.
(function () {
  "use strict";

  const es = {
    // Top bar and connection
    "DuneBox Dashboard": "Panel de DuneBox",
    "Sensor: waiting": "Sensor: esperando",
    "Sensor: unknown": "Sensor: desconocido",
    "DuneBox: not linked": "DuneBox: sin conectar",
    "DuneBox: link off": "DuneBox: enlace apagado",
    "DuneBox: running": "DuneBox: funcionando",
    "DuneBox: needs setup": "DuneBox: falta configurar",
    "Connecting…": "Conectando…",
    "Connected": "Conectado",
    "Offline": "Sin conexión",
    "Dashboard language": "Idioma del panel",
    "Voice": "Voz",
    "Listening…": "Escuchando…",
    "Open on a tablet": "Abrir en una tableta",
    "Can't reach the sandbox.": "No se puede conectar con el arenero.",
    "On the sandbox PC, open sandcam and press": "En el PC del arenero, abre sandcam y pulsa",
    "to turn on the dashboard. Trying": "para activar el panel. Intentando",
    "Retry now": "Reintentar",
    "Enter the dashboard PIN": "Escribe el PIN del panel",
    "The PIN is shown on the sandbox screen when you press": "El PIN aparece en la pantalla del arenero al pulsar",
    ", and saved as": ", y se guarda como",
    "in": "en",
    "Connect": "Conectar",
    "That PIN didn't work.": "Ese PIN no es correcto.",

    // Live view
    "Live sand": "Arena en directo",
    "Waiting for frames": "Esperando imágenes",
    "No connection": "Sin conexión",
    "View": "Vista",
    "Live elevation map of the sand": "Mapa de elevación de la arena en directo",
    "3D view of the sand. Drag or use arrow keys to orbit, scroll or pinch to zoom.":
      "Vista 3D de la arena. Arrastra o usa las flechas para girar; desplaza o pellizca para acercar.",
    "The live view appears here once the sandbox is connected.":
      "La vista en directo aparece aquí cuando el arenero está conectado.",
    "Sensor": "Sensor",
    "Simulator": "Simulador",
    "Sandbox frame rate": "Imágenes por segundo",
    "Below sea level": "Bajo el nivel del mar",
    "Running for": "En marcha desde hace",
    "Activity": "Actividad",
    "Actions you take here, and what the sandbox said back, show up in this list.":
      "Aquí aparecen las acciones que hagas y lo que responde el arenero.",

    // sandcam: world
    "Sandbox controls": "Controles del arenero",
    "Python · creatures and games": "Python · criaturas y juegos",
    "World": "Mundo",
    "Color theme": "Colores",
    "Terrain": "Relieve",
    "Heat map": "Mapa de calor",
    "Greyscale": "Escala de grises",
    "Desert": "Desierto",
    "Contour lines": "Curvas de nivel",
    "Elevation labels": "Alturas",
    "Spacing": "Separación",
    "Sea level": "Nivel del mar",
    "Creatures": "Criaturas",
    "Change creature set": "Cambiar criaturas",
    "Set": "Grupo",
    "Modern": "Modernas",
    "Plants grow": "Crecen plantas",
    "Plants grow (ecosystem)": "Crecen plantas (ecosistema)",
    "Day and night": "Día y noche",
    "Cycle speed": "Velocidad del ciclo",
    "Slower": "Más lento",
    "Faster": "Más rápido",
    "Day and night cycle": "Ciclo de día y noche",
    "Sound": "Sonido",

    // Events and games
    "Events": "Eventos",
    "Erupt volcano": "Erupción",
    "Earthquake": "Terremoto",
    "No volcanoes yet. Erupting places one at the centre.":
      "Aún no hay volcanes. Al pulsar Erupción se crea uno en el centro.",
    "A volcano is erupting.": "Un volcán está en erupción.",
    "Games": "Juegos",
    "Start": "Empezar",
    "End game": "Terminar juego",
    "Score": "Puntos",
    "Time left": "Tiempo restante",
    "No limit": "Sin límite",
    "Build a Dam": "Construye una presa",
    "Volcano Defense": "Defensa del volcán",
    "Watershed Puzzle": "Puzle de cuencas",
    "Biome Sculpt": "Esculpe biomas",
    "Terrain Challenge": "Reto de relieve",
    "pick a landscape to rebuild": "elige un paisaje para reconstruir",
    "Island": "Isla",
    "Valley": "Valle",
    "Two peaks": "Dos picos",

    // Classroom
    "Classroom": "Aula",
    "Steps": "Pasos",
    "Back": "Atrás",
    "Next step": "Siguiente paso",
    "End lesson": "Terminar lección",
    "A presentation clicker works too: Page Down for the next step.":
      "También funciona un mando de presentaciones: Av Pág para el siguiente paso.",
    "Language on the sand": "Idioma en la arena",
    "Teams": "Equipos",
    "Off": "No",
    "Show scores on the sand": "Mostrar puntos en la arena",
    "Reset scores": "Poner a cero",
    "Goal reached": "Objetivo conseguido",
    "Give the last game's points to:": "Dar los puntos del último juego a:",

    // Setup
    "Setup": "Configuración",
    "Setup check": "Comprobación",
    "Measuring…": "Midiendo…",
    "Depth camera": "Cámara de profundidad",
    "Not found. The simulator is standing in.": "No encontrada. Se usa el simulador.",
    "Sand in view": "Arena a la vista",
    "Surface steadiness": "Estabilidad de la superficie",
    "Frame rate": "Imágenes por segundo",
    "Projector: sand area": "Proyector: zona de arena",
    "Projector: alignment": "Proyector: alineación",
    "Detected": "Detectada",
    "Not detected yet": "Aún no detectada",
    "Calibrated": "Calibrado",
    "Not calibrated yet": "Aún sin calibrar",
    "Detect": "Detectar",
    "Calibrate": "Calibrar",
    "Use Stable": "Usar Estable",
    "Smoothing": "Suavizado",
    "Responsive": "Rápido",
    "Balanced": "Equilibrado",
    "Stable": "Estable",
    "Responsive follows hands quickly; Stable hides flicker but lags.":
      "Rápido sigue las manos al momento; Estable evita parpadeos pero va con retraso.",
    "Custom values from the sandcam sidebar. Pick a preset to replace them.":
      "Valores personalizados desde sandcam. Elige una opción para sustituirlos.",
    "Calibrate depth": "Calibrar profundidad",
    "Reset terrain": "Reiniciar relieve",
    "Calibrate with the sand flat and hands clear. Current range":
      "Calibra con la arena lisa y sin manos encima. Rango actual",

    // Unattended
    "Unattended": "Sin supervisión",
    "Opening hours": "Horario",
    "Hours": "Horas",
    "Opening time": "Hora de apertura",
    "Closing time": "Hora de cierre",
    "Open days": "Días abiertos",
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
    "Outside opening hours the projection goes dark and the projector switches off.":
      "Fuera del horario la proyección se apaga y el proyector también.",
    "Wake until next change": "Encender hasta el próximo cambio",
    "Projector (PJLink)": "Proyector (PJLink)",
    "IP address, e.g. 192.168.1.50": "Dirección IP, p. ej. 192.168.1.50",
    "On": "Encender",
    "Turns a networked projector on and off with the opening hours. Set a password in sandcam-settings.json if it needs one.":
      "Enciende y apaga un proyector en red según el horario. Si necesita contraseña, ponla en sandcam-settings.json.",
    "Projector set. Power state appears after the first command.":
      "Proyector configurado. Su estado aparece tras la primera orden.",
    "Reconnect camera automatically": "Reconectar la cámara automáticamente",

    // Physical buttons
    "Physical buttons": "Botones físicos",
    "Press a button on a USB keypad or the Arduino and it appears here. Choose what it does.":
      "Pulsa un botón del teclado USB o del Arduino y aparecerá aquí. Elige qué hace.",
    "Arduino buttons": "Botones Arduino",
    "For arcade buttons wired to an Arduino running hardware/buttons/buttons.ino.":
      "Para botones arcade conectados a un Arduino con hardware/buttons/buttons.ino.",
    "Looking for the Arduino…": "Buscando el Arduino…",
    "No Arduino found. Plug it in over USB.": "No se encuentra el Arduino. Conéctalo por USB.",
    "Nothing": "Nada",
    "Erupt a volcano": "Erupción de un volcán",
    "Next colour theme": "Siguientes colores",
    "Contour lines on/off": "Curvas de nivel sí/no",
    "Creatures on/off": "Criaturas sí/no",
    "Day and night on/off": "Día y noche sí/no",
    "Raise the sea": "Subir el mar",
    "Lower the sea": "Bajar el mar",
    "Start the terrain challenge": "Empezar el reto de relieve",
    "Save the terrain": "Guardar el relieve",
    "Wake the sandbox": "Encender el arenero",
    "DuneBox: water on/off": "DuneBox: agua sí/no",
    "DuneBox: lava on/off": "DuneBox: lava sí/no",
    "DuneBox: erupt volcano": "DuneBox: erupción",
    "DuneBox: drain water": "DuneBox: vaciar agua",

    // Saved terrains
    "Saved terrains": "Relieves guardados",
    "Save snapshot": "Guardar captura",
    "Saves the sand as a DEM (.asc, heights in mm, opens in QGIS), an image, and a file you can rebuild later.":
      "Guarda la arena como MDE (.asc, alturas en mm, se abre en QGIS), una imagen y un archivo para reconstruirla después.",
    "Load": "Cargar",
    "Rebuild": "Reconstruir",
    "Timelapse": "Timelapse",
    "Timelapse recording": "Grabación de timelapse",

    // DuneBox (C++)
    "C++ · water and lava": "C++ · agua y lava",
    "Not linked": "Sin conectar",
    "Link off": "Enlace apagado",
    "Simulation": "Simulación",
    "Not linked.": "Sin conectar.",
    "Start DuneBox (Magic-Sand) on this PC. It links to sandcam automatically and its water, lava and theme controls appear here.":
      "Abre DuneBox (Magic-Sand) en este PC. Se conecta solo con sandcam y aquí aparecen sus controles de agua, lava y colores.",
    "Running": "Funcionando",
    "Starting": "Arrancando",
    "Setup: not calibrated yet": "Configuración: aún sin calibrar",
    "Calibrating": "Calibrando",
    "Follow the prompts on the projector.": "Sigue las indicaciones del proyector.",
    "Confirm": "Confirmar",
    "Cancel": "Cancelar",
    "Water simulation": "Simulación de agua",
    "Evaporation": "Evaporación",
    "Slow": "Lenta",
    "Fast": "Rápida",
    "Lakes slowly dry up so the sand doesn't flood over a long session.":
      "Los lagos se secan poco a poco para que la arena no se inunde en sesiones largas.",
    "Rain from hands": "Lluvia con las manos",
    "Show erosion": "Mostrar erosión",
    "Sensor": "Sensor",
    "Share this sensor with DuneBox": "Compartir este sensor con DuneBox",
    "Lets DuneBox use the sensor sandcam is running, such as an Orbbec Femto or RealSense.":
      "Permite que DuneBox use el sensor de sandcam, como un Orbbec Femto o un RealSense.",
    "DuneBox is receiving depth from this sensor.": "DuneBox está recibiendo la profundidad de este sensor.",
    "Waiting for DuneBox on port 9877. In DuneBox, set kinectVersion to 4 in settings/kinectProjectorSettings.xml.":
      "Esperando a DuneBox en el puerto 9877. En DuneBox, pon kinectVersion a 4 en settings/kinectProjectorSettings.xml.",
    "Sharing the sensor with DuneBox": "Compartiendo el sensor con DuneBox",
    "Stopped sharing the sensor": "Ya no se comparte el sensor",
    "Fast water scars the sand dark and drops pale sediment where it slows. Marks fade, and reshaping the sand clears them.":
      "El agua rápida marca la arena de oscuro y deja sedimento claro donde se frena. Las marcas se desvanecen y se borran al mover la arena.",
    "Drain all water": "Vaciar toda el agua",
    "Lava instead of water": "Lava en vez de agua",
    "Lava mode": "Modo lava",
    "DuneBox day and night": "Día y noche en DuneBox",
    "Next theme": "Siguientes colores",
    "Start sandbox": "Iniciar arenero",
    "Recalibrate everything": "Volver a calibrar todo",

    // Popovers
    "Press": "Pulsa",
    "for keyboard shortcuts.": "para ver los atajos de teclado.",
    "QR code linking to this dashboard": "Código QR que abre este panel",
    "Scan with a phone or tablet on the same Wi-Fi, or open:":
      "Escanéalo con un móvil o tableta en la misma wifi, o abre:",
    "Copy": "Copiar",
    "Address copied": "Dirección copiada",
    "This dashboard only accepts connections from the sandbox PC.":
      "Este panel solo acepta conexiones desde el PC del arenero.",
    "To use a tablet, set": "Para usar una tableta, pon",
    "and restart sandcam. A PIN keeps it private.": "y reinicia sandcam. Un PIN lo mantiene privado.",
    "Keyboard shortcuts": "Atajos de teclado",
    "Start a game": "Empezar un juego",
    "Timelapse on/off": "Timelapse sí/no",
    "Notifications": "Notificaciones",
    "Not connected to the sandbox.": "No hay conexión con el arenero.",
    "No response from the sandbox. Check that sandcam is still running.":
      "El arenero no responde. Comprueba que sandcam sigue abierto.",
  };

  const DICTIONARIES = { es };
  const ATTRS = ["aria-label", "placeholder", "title"];
  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "TEXTAREA"]);
  // node -> { en: English source, shown: text we last wrote }
  const textState = new WeakMap();
  const attrState = new WeakMap();
  let lang = "en";

  function lookup(english) {
    if (lang === "en") return english;
    const dict = DICTIONARIES[lang];
    return (dict && dict[english]) || english;
  }

  function translateText(node) {
    const parent = node.parentElement;
    if (!parent || SKIP.has(parent.tagName) || parent.closest("[translate=no]")) return;
    const raw = node.nodeValue;
    const st = textState.get(node);
    const english = st && st.shown === raw ? st.en : raw.trim();
    if (!english || !/[A-Za-z]/.test(english)) return;
    const out = raw.replace(raw.trim(), () => lookup(english));
    textState.set(node, { en: english, shown: out });
    if (out !== raw) node.nodeValue = out;
  }

  function translateAttrs(el) {
    let st = attrState.get(el);
    for (const name of ATTRS) {
      const raw = el.getAttribute(name);
      if (!raw) continue;
      if (!st) attrState.set(el, (st = {}));
      const prev = st[name];
      const english = prev && prev.shown === raw ? prev.en : raw;
      const out = lookup(english);
      st[name] = { en: english, shown: out };
      if (out !== raw) el.setAttribute(name, out);
    }
  }

  function walk(root) {
    if (root.nodeType === Node.TEXT_NODE) return translateText(root);
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    translateAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) translateText(n);
    for (const el of root.querySelectorAll("[aria-label],[placeholder],[title]")) translateAttrs(el);
  }

  const observer = new MutationObserver((records) => {
    if (lang === "en") return;
    for (const r of records) {
      if (r.type === "characterData") translateText(r.target);
      else if (r.type === "attributes") translateAttrs(r.target);
      else r.addedNodes.forEach(walk);
    }
  });

  function setLanguage(next) {
    lang = DICTIONARIES[next] ? next : "en";
    document.documentElement.lang = lang;
    document.title = lookup("DuneBox Dashboard");
    walk(document.body);
    observer.disconnect();
    if (lang !== "en") {
      observer.observe(document.body, {
        subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ATTRS,
      });
    }
  }

  window.DuneI18n = {
    setLanguage,
    t: lookup,
    get language() { return lang; },
    languages: ["en", ...Object.keys(DICTIONARIES)],
  };
})();
