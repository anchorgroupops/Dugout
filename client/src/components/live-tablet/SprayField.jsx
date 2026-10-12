import { DEFAULT_FIELD, playTypeGroup, zonePercents } from './tabletHelpers.js';

// Colour by contact type. Hits are filled, outs/errors are hollow rings.
const TYPE_COLOUR = { ground: '#ffd23f', line: '#ff6b6b', fly: '#4cc9f0', other: '#e0e0e0' };
const TYPE_LABEL = { ground: 'Ground', line: 'Line', fly: 'Fly', other: 'Other' };

const R = Math.SQRT1_2; // cos 45
function onLine(home, dist, side) {
  const d = dist * R;
  return [home[0] + side * d, home[1] - d];
}

export default function SprayField({ field = DEFAULT_FIELD, spray = [] }) {
  const { width, height, home } = { ...DEFAULT_FIELD, ...field };
  const fenceR = 250;
  const dirtR = 125;
  const [fr, fy] = onLine(home, fenceR, 1);
  const [fl] = onLine(home, fenceR, -1);
  const [dr, dy] = onLine(home, dirtR, 1);
  const [dl] = onLine(home, dirtR, -1);
  const b1 = onLine(home, 95, 1);
  const b3 = onLine(home, 95, -1);
  const b2 = [home[0], home[1] - 95 * Math.SQRT2];
  const mound = [home[0], home[1] - 95 * Math.SQRT2 * 0.5];
  const pct = zonePercents(spray, home);
  const present = [...new Set(spray.map((p) => playTypeGroup(p.play_type)))];

  return (
    <div className="dt-field-wrap">
      <svg className="dt-field" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Spray chart" preserveAspectRatio="xMidYMid meet">
        <rect width={width} height={height} fill="#0b1f14" />
        <path d={`M ${home[0]} ${home[1]} L ${fl} ${fy} A ${fenceR} ${fenceR} 0 0 1 ${fr} ${fy} Z`} fill="#1d5c36" />
        <path d={`M ${home[0]} ${home[1]} L ${dl} ${dy} A ${dirtR} ${dirtR} 0 0 1 ${dr} ${dy} Z`} fill="#8a5a33" />
        <polygon points={`${home} ${b1} ${b2} ${b3}`} fill="#1d5c36" />
        <path d={`M ${fl} ${fy} A ${fenceR} ${fenceR} 0 0 1 ${fr} ${fy}`} fill="none" stroke="#fff" strokeWidth="3" />
        <line x1={home[0]} y1={home[1]} x2={fl} y2={fy} stroke="#fff" strokeWidth="2" />
        <line x1={home[0]} y1={home[1]} x2={fr} y2={fy} stroke="#fff" strokeWidth="2" />
        <circle cx={mound[0]} cy={mound[1]} r="14" fill="#8a5a33" stroke="#fff" strokeWidth="1.5" />
        {[b1, b2, b3].map((b, i) => (
          <rect key={i} x={b[0] - 6} y={b[1] - 6} width="12" height="12" fill="#fff" transform={`rotate(45 ${b[0]} ${b[1]})`} />
        ))}
        <polygon points={`${home[0] - 7},${home[1] - 2} ${home[0] + 7},${home[1] - 2} ${home[0] + 7},${home[1] + 4} ${home[0]},${home[1] + 10} ${home[0] - 7},${home[1] + 4}`} fill="#fff" />
        {[...spray].sort((a, b) => (a.hit - b.hit) || (a.today - b.today)).map((p, i) => {
          const colour = TYPE_COLOUR[playTypeGroup(p.play_type)];
          return (
            <g key={i}>
              {p.today && <circle cx={p.x} cy={p.y} r="13" fill="none" stroke="#fff" strokeWidth="3" strokeDasharray="4 3" />}
              {p.hit
                ? <circle cx={p.x} cy={p.y} r="8" fill={colour} stroke="#000" strokeWidth="1.5" />
                : <circle cx={p.x} cy={p.y} r="7" fill="rgba(0,0,0,0.55)" stroke={colour} strokeWidth="3.5" />}
            </g>
          );
        })}
        {spray.length === 0 && (
          <text x={width / 2} y={height / 2 - 20} textAnchor="middle" fill="#fff" fontSize="18" fontWeight="700">No balls in play on record</text>
        )}
      </svg>
      <div className="dt-legend">
        {present.map((g) => (
          <span key={g}><i style={{ background: TYPE_COLOUR[g] }} />{TYPE_LABEL[g]}</span>
        ))}
        {spray.length > 0 && <span><i className="dt-leg-hit" />Hit</span>}
        {spray.length > 0 && <span><i className="dt-leg-out" />Out</span>}
        {spray.some((p) => p.today) && <span><i className="dt-leg-today" />Today</span>}
        {pct && <span className="dt-zones">Left {pct.left}% · Centre {pct.centre}% · Right {pct.right}%</span>}
      </div>
    </div>
  );
}
