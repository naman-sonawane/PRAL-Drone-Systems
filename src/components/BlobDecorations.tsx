'use client';

import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

const BLOBS = ['orange.png', 'purple.png', 'red.png', 'teal.png'];

// Anchor points around the edges/corners of the viewport. Each blob is hung
// off one of these so it bleeds in from the side rather than floating dead-center.
const ANCHORS = [
  { cx: 0, cy: 0 },     // top-left
  { cx: 1, cy: 0 },     // top-right
  { cx: 0, cy: 1 },     // bottom-left
  { cx: 1, cy: 1 },     // bottom-right
  { cx: 0.5, cy: 0 },   // top-center
  { cx: 0.5, cy: 1 },   // bottom-center
  { cx: 0, cy: 0.5 },   // left-center
  { cx: 1, cy: 0.5 },   // right-center
];

interface BlobPosition {
  id: number;
  blob: string;
  left: number; // px
  top: number; // px
  size: number; // px
  driftY: number[];
  driftX: number[];
  duration: number;
  delay: number;
}

// Simple seeded PRNG so each page gets a distinct-but-stable layout (avoids the
// hydration mismatch you'd get from Math.random during render).
function makeRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

function hashString(str: string) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function BlobDecorations() {
  const pathname = usePathname();
  const [blobs, setBlobs] = useState<BlobPosition[]>([]);

  useEffect(() => {
    const rng = makeRng(hashString(pathname || '/'));
    const w = window.innerWidth;
    const h = window.innerHeight;

    // Pick a random subset of anchors so colors land in different places per page.
    const anchorOrder = [...ANCHORS].sort(() => rng() - 0.5);
    const colorOrder = [...BLOBS].sort(() => rng() - 0.5);
    const blobCount = 4 + Math.floor(rng() * 3); // 4-6 blobs

    const generated: BlobPosition[] = [];
    for (let i = 0; i < blobCount; i++) {
      const anchor = anchorOrder[i % anchorOrder.length];
      const blob = colorOrder[i % colorOrder.length];
      const size = rng() * 220 + 180; // 180-400px

      // Center the blob on its anchor, then let it bleed ~40% off the edge so a
      // chunk stays visible. Add jitter so repeated anchors don't overlap exactly.
      const jitterX = (rng() - 0.5) * size * 0.6;
      const jitterY = (rng() - 0.5) * size * 0.6;
      const left = anchor.cx * w - size / 2 + jitterX;
      const top = anchor.cy * h - size / 2 + jitterY;

      generated.push({
        id: i,
        blob,
        left,
        top,
        size,
        driftY: [0, rng() * -25 - 5, rng() * -15, rng() * -28 - 5, rng() * -10],
        driftX: [0, rng() * 18 - 4, rng() * -16, rng() * 18, rng() * -10],
        duration: 14 + rng() * 12,
        delay: rng() * 2,
      });
    }

    setBlobs(generated);
  }, [pathname]);

  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden -z-10">
      {blobs.map((blob) => (
        <motion.div
          key={`${pathname}-${blob.id}`}
          className="absolute"
          style={{
            left: blob.left,
            top: blob.top,
            width: blob.size,
            height: blob.size,
          }}
          initial={{ opacity: 0, scale: 0.2 }}
          animate={{
            opacity: 0.5,
            scale: [0.2, 1.12, 1],
            y: blob.driftY,
            x: blob.driftX,
          }}
          transition={{
            opacity: { duration: 0.7, delay: blob.delay, ease: 'easeOut' },
            scale: {
              duration: 0.9,
              delay: blob.delay,
              ease: [0.34, 1.56, 0.64, 1], // back-out: pops past 1 then settles
              times: [0, 0.6, 1],
            },
            y: {
              duration: blob.duration,
              delay: blob.delay,
              repeat: Infinity,
              ease: 'easeInOut',
            },
            x: {
              duration: blob.duration + 3,
              delay: blob.delay,
              repeat: Infinity,
              ease: 'easeInOut',
            },
          }}
        >
          <img
            src={`/blobs/${blob.blob}`}
            alt=""
            className="w-full h-full object-contain"
            style={{ filter: 'blur(1px)' }}
          />
        </motion.div>
      ))}
    </div>
  );
}
