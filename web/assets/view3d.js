// 3D terrain view: WebGL2, no libraries. The greyscale depth frame becomes a
// height texture displaced on a grid mesh, coloured with the theme LUT.
(() => {
  "use strict";

  const VS = `#version 300 es
  in vec2 aGrid;                 // 0..1 across the sand
  uniform sampler2D uHeight;
  uniform mat4 uMvp;
  uniform float uScale;
  uniform vec2 uTexel;
  uniform float uAspect;
  out float vH;
  out vec3 vNormal;
  float h(vec2 uv) { return texture(uHeight, uv).r; }
  void main() {
    vec2 uv = vec2(aGrid.x, aGrid.y);
    float c = h(uv);
    float dx = h(uv + vec2(uTexel.x, 0.0)) - h(uv - vec2(uTexel.x, 0.0));
    float dy = h(uv + vec2(0.0, uTexel.y)) - h(uv - vec2(0.0, uTexel.y));
    vNormal = normalize(vec3(-dx * uScale / (2.0 * uTexel.x * uAspect), 1.0, -dy * uScale / (2.0 * uTexel.y)));
    vH = c;
    vec3 pos = vec3((aGrid.x - 0.5) * uAspect, c * uScale, aGrid.y - 0.5);
    gl_Position = uMvp * vec4(pos, 1.0);
  }`;

  const FS = `#version 300 es
  precision highp float;
  in float vH;
  in vec3 vNormal;
  uniform sampler2D uLut;
  uniform float uContour;        // interval, 0 = off
  uniform float uSea;
  out vec4 outColor;
  void main() {
    vec3 base = texture(uLut, vec2(clamp(vH, 0.0, 1.0), 0.5)).rgb;
    vec3 L = normalize(vec3(-0.5, 0.9, -0.4));
    float diffuse = max(dot(normalize(vNormal), L), 0.0);
    vec3 col = base * (0.45 + 0.65 * diffuse);
    if (uContour > 0.0 && vH >= uSea) {
      float f = vH / uContour;
      float w = fwidth(f);
      float line = 1.0 - smoothstep(0.0, w * 1.2, abs(fract(f - 0.5) - 0.5));
      col *= 1.0 - 0.65 * line;
    }
    outColor = vec4(col, 1.0);
  }`;

  // ── tiny mat4 helpers (column-major) ──
  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
  }
  function lookAt(eye, target, up) {
    const z = norm(sub(eye, target)), x = norm(cross(up, z)), y = cross(z, x);
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
  }
  function mul(a, b) {
    const o = new Array(16).fill(0);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
    return o;
  }
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

  function compile(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }

  function create(canvas) {
    const gl = canvas.getContext("webgl2", { antialias: true });
    if (!gl) return null;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    const loc = (n) => gl.getUniformLocation(prog, n);
    const u = { mvp: loc("uMvp"), scale: loc("uScale"), texel: loc("uTexel"), aspect: loc("uAspect"),
      height: loc("uHeight"), lut: loc("uLut"), contour: loc("uContour"), sea: loc("uSea") };

    // Grid: GW x GH vertices, drawn as indexed triangles
    const GW = 160, GH = 120;
    const verts = new Float32Array(GW * GH * 2);
    for (let y = 0; y < GH; y++) for (let x = 0; x < GW; x++) {
      verts[(y * GW + x) * 2] = x / (GW - 1);
      verts[(y * GW + x) * 2 + 1] = y / (GH - 1);
    }
    const idx = new Uint32Array((GW - 1) * (GH - 1) * 6);
    let k = 0;
    for (let y = 0; y < GH - 1; y++) for (let x = 0; x < GW - 1; x++) {
      const i = y * GW + x;
      idx.set([i, i + GW, i + 1, i + 1, i + GW, i + GW + 1], k);
      k += 6;
    }
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
    const aGrid = gl.getAttribLocation(prog, "aGrid");
    gl.enableVertexAttribArray(aGrid);
    gl.vertexAttribPointer(aGrid, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);

    function texture(unit) {
      const t = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      return t;
    }
    const heightTex = texture(0);
    const lutTex = texture(1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([128, 128, 128, 255]));
    let frameW = 1, frameH = 1, hasFrame = false;
    let opts = { contour: 0.05, sea: 0.46, scale: 0.28 };

    // Orbit camera
    let yaw = -0.45, pitch = 0.8, dist = 1.45;
    const pointers = new Map();
    let pinch = 0;
    canvas.style.touchAction = "none";
    canvas.addEventListener("pointerdown", (e) => { canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.clientX, e.clientY]); });
    canvas.addEventListener("pointerup", (e) => { pointers.delete(e.pointerId); pinch = 0; });
    canvas.addEventListener("pointercancel", (e) => { pointers.delete(e.pointerId); pinch = 0; });
    canvas.addEventListener("pointermove", (e) => {
      const prev = pointers.get(e.pointerId);
      if (!prev) return;
      pointers.set(e.pointerId, [e.clientX, e.clientY]);
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch) dist = Math.min(4, Math.max(0.8, dist * pinch / d));
        pinch = d;
      } else {
        yaw += (e.clientX - prev[0]) * 0.008;
        pitch = Math.min(1.45, Math.max(0.15, pitch + (e.clientY - prev[1]) * 0.006));
      }
      draw();
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      dist = Math.min(4, Math.max(0.8, dist * Math.exp(e.deltaY * 0.001)));
      draw();
    }, { passive: false });
    canvas.addEventListener("keydown", (e) => {
      const step = { ArrowLeft: [-0.1, 0], ArrowRight: [0.1, 0], ArrowUp: [0, 0.08], ArrowDown: [0, -0.08] }[e.key];
      if (!step) return;
      e.preventDefault();
      yaw += step[0];
      pitch = Math.min(1.45, Math.max(0.15, pitch + step[1]));
      draw();
    });

    function draw() {
      if (!hasFrame) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0.039, 0.039, 0.039, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.useProgram(prog);
      const aspect = frameW / frameH;
      const eye = [Math.sin(yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist];
      const mvp = mul(perspective(0.8, w / Math.max(1, h), 0.05, 20), lookAt(eye, [0, 0.08, 0], [0, 1, 0]));
      gl.uniformMatrix4fv(u.mvp, false, mvp);
      gl.uniform1f(u.scale, opts.scale);
      gl.uniform2f(u.texel, 1 / frameW, 1 / frameH);
      gl.uniform1f(u.aspect, aspect);
      gl.uniform1i(u.height, 0);
      gl.uniform1i(u.lut, 1);
      gl.uniform1f(u.contour, opts.contour);
      gl.uniform1f(u.sea, opts.sea);
      gl.bindVertexArray(vao);
      gl.drawElements(gl.TRIANGLES, idx.length, gl.UNSIGNED_INT, 0);
    }

    return {
      setLut(rgba) {
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, lutTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
        draw();
      },
      // source: a canvas holding the greyscale frame (height in the red channel)
      update(source, w, h, options) {
        opts = { ...opts, ...options };
        frameW = w; frameH = h; hasFrame = true;
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, heightTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
        draw();
      },
      draw,
    };
  }

  window.DuneView3D = { create };
})();
