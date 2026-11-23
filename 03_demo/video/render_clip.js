// Render a clip: node render_clip.js <clip.html> <out.mp4> [stills: comma-separated seconds]
// The page defines window.render(t) and window.DURATION (seconds). 30 fps, 1920x1080, H.264.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
(async () => {
  const [html, out, stills = ''] = process.argv.slice(2);
  const FPS = 30;
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto('file://' + path.resolve(html));
  await p.waitForTimeout(500);
  const DUR = await p.evaluate(() => window.DURATION);
  for (const s of stills.split(',').filter(Boolean)) {   // stills first, as PNG next to the video
    await p.evaluate(t => render(t), +s);
    await p.screenshot({ path: out.replace(/\.(mp4|png)$/, '') + `_${s}s.png` });
  }
  if (out.endsWith('.mp4')) {
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'medium', out], { stdio: ['pipe', 'ignore', 'inherit'] });
    for (let i = 0; i < FPS * DUR; i++) {
      await p.evaluate(t => render(t), i / FPS);
      const buf = await p.screenshot({ type: 'jpeg', quality: 92 });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  }
  await b.close();
})();
