import { useEffect, useRef } from "react";

export default function Scene3D() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    let raf;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    // Floating wireframe shapes
    const shapes = Array.from({ length: 18 }, (_, i) => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      size: 20 + Math.random() * 50,
      rotX: Math.random() * Math.PI * 2,
      rotY: Math.random() * Math.PI * 2,
      rotZ: Math.random() * Math.PI * 2,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      vrX: (Math.random() - 0.5) * 0.008,
      vrY: (Math.random() - 0.5) * 0.008,
      vrZ: (Math.random() - 0.5) * 0.008,
      type: i % 3, // 0=cube, 1=diamond, 2=triangle
      alpha: 0.08 + Math.random() * 0.12,
    }));

    const project = (x, y, z, cx, cy) => {
      const fov = 300;
      const scale = fov / (fov + z);
      return { x: cx + x * scale, y: cy + y * scale, scale };
    };

    const drawCube = (ctx, cx, cy, s, rX, rY, rZ, alpha) => {
      const verts = [
        [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
        [-s, -s,  s], [s, -s,  s], [s, s,  s], [-s, s,  s],
      ];
      const edges = [
        [0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]
      ];
      const cosX = Math.cos(rX), sinX = Math.sin(rX);
      const cosY = Math.cos(rY), sinY = Math.sin(rY);
      const cosZ = Math.cos(rZ), sinZ = Math.sin(rZ);

      const rotated = verts.map(([x, y, z]) => {
        let y1 = y * cosX - z * sinX, z1 = y * sinX + z * cosX;
        let x2 = x * cosY + z1 * sinY, z2 = -x * sinY + z1 * cosY;
        let x3 = x2 * cosZ - y1 * sinZ, y3 = x2 * sinZ + y1 * cosZ;
        return [x3, y3, z2];
      });

      ctx.strokeStyle = `rgba(255, 30, 100, ${alpha})`;
      ctx.lineWidth = 0.8;
      edges.forEach(([a, b]) => {
        const p1 = project(rotated[a][0], rotated[a][1], rotated[a][2], cx, cy);
        const p2 = project(rotated[b][0], rotated[b][1], rotated[b][2], cx, cy);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      });
    };

    const drawDiamond = (ctx, cx, cy, s, rZ, alpha) => {
      const pts = 6;
      ctx.strokeStyle = `rgba(180, 0, 255, ${alpha})`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      for (let i = 0; i <= pts; i++) {
        const a = (i / pts) * Math.PI * 2 + rZ;
        const r = i % 2 === 0 ? s : s * 0.5;
        i === 0 ? ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r)
                : ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      }
      ctx.closePath();
      ctx.stroke();
    };

    const drawTriangle = (ctx, cx, cy, s, rZ, alpha) => {
      ctx.strokeStyle = `rgba(255, 80, 150, ${alpha})`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      for (let i = 0; i < 3; i++) {
        const a = (i / 3) * Math.PI * 2 + rZ;
        i === 0 ? ctx.moveTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s)
                : ctx.lineTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s);
      }
      ctx.closePath();
      ctx.stroke();
    };

    const tick = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      shapes.forEach(sh => {
        sh.x += sh.vx;
        sh.y += sh.vy;
        sh.rotX += sh.vrX;
        sh.rotY += sh.vrY;
        sh.rotZ += sh.vrZ;
        if (sh.x < -100) sh.x = canvas.width + 100;
        if (sh.x > canvas.width + 100) sh.x = -100;
        if (sh.y < -100) sh.y = canvas.height + 100;
        if (sh.y > canvas.height + 100) sh.y = -100;

        if (sh.type === 0) drawCube(ctx, sh.x, sh.y, sh.size, sh.rotX, sh.rotY, sh.rotZ, sh.alpha);
        else if (sh.type === 1) drawDiamond(ctx, sh.x, sh.y, sh.size, sh.rotZ, sh.alpha);
        else drawTriangle(ctx, sh.x, sh.y, sh.size, sh.rotZ, sh.alpha);
      });

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="scene3d-canvas" />;
}
