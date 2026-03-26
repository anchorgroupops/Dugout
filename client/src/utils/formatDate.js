const TZ = 'America/New_York';

export const formatDateTime = (dateStr) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleString('en-US', { timeZone: TZ });
};

export const formatDateShort = (dateStr, options = {}) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString('en-US', { timeZone: TZ, ...options });
};

/** Format a date string as MM/DD/YYYY */
export const formatDateMMDDYYYY = (dateStr) => {
  if (!dateStr) return '';
  const d = new Date(dateStr + (dateStr.includes('T') ? '' : 'T12:00:00'));
  return d.toLocaleDateString('en-US', {
    timeZone: TZ,
    month: '2-digit',
    day: '2-digit',
    year: 'numeric',
  });
};

export const formatTime = (dateStr, options = {}) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString('en-US', { timeZone: TZ, ...options });
};

export const getTodayEST = () => {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(new Date());
};

/** Format a date as a relative time string (e.g. "3 min ago", "2 hrs ago") */
export const formatRelative = (dateStr) => {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs} hr${hrs > 1 ? 's' : ''} ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`;
  return formatDateTime(dateStr);
};

/** Stat tooltip abbreviation map */
export const STAT_GLOSSARY = {
  PA: 'Plate Appearances',
  AB: 'At Bats',
  H: 'Hits',
  '1B': 'Singles',
  '2B': 'Doubles',
  '3B': 'Triples',
  HR: 'Home Runs',
  R: 'Runs Scored',
  RBI: 'Runs Batted In',
  BB: 'Walks (Base on Balls)',
  HBP: 'Hit By Pitch',
  SO: 'Strikeouts',
  K: 'Strikeouts',
  SB: 'Stolen Bases',
  AVG: 'Batting Average (H/AB)',
  OBP: 'On-Base Percentage',
  SLG: 'Slugging Percentage',
  OPS: 'On-Base Plus Slugging',
  BABIP: 'Batting Avg on Balls In Play',
  'QAB%': 'Quality At-Bat Percentage',
  'BB/K': 'Walk-to-Strikeout Ratio',
  TB: 'Total Bases',
  'FB%': 'Fly Ball Percentage',
  'GB%': 'Ground Ball Percentage',
  'LD%': 'Line Drive Percentage',
  'PS/PA': 'Pitches per Plate Appearance',
  IP: 'Innings Pitched',
  ERA: 'Earned Run Average',
  WHIP: 'Walks+Hits per Inning Pitched',
  BAA: 'Batting Average Against',
  NP: 'Number of Pitches',
  'W-L': 'Win-Loss Record',
  FPCT: 'Fielding Percentage',
  TC: 'Total Chances',
  PO: 'Putouts',
  E: 'Errors',
  A: 'Assists',
  INN: 'Innings',
  'CS%': 'Caught Stealing Percentage',
  PB: 'Passed Balls',
  'SB-ATT': 'Stolen Base Attempts',
  GP: 'Games Played',
  GS: 'Games Started',
  SV: 'Saves',
  BF: 'Batters Faced',
  '#P': 'Number of Pitches',
  KL: 'Strikeouts Looking',
  WP: 'Wild Pitches',
  BK: 'Balks',
  LOB: 'Left on Base',
  PIK: 'Pickoffs',
  'S%': 'Strike Percentage',
  'P/IP': 'Pitches per Inning',
  'P/BF': 'Pitches per Batter Faced',
  'FPS%': 'First Pitch Strike Percentage',
  'FPSw%': 'First Pitch Strike — Whiff',
  'FPSo%': 'First Pitch Strike — Out',
  'FPSh%': 'First Pitch Strike — Hit',
  LOO: 'Lead-Off Outs',
  '1st2Out': 'Lead-Off Outs in First Two',
  '1-2-3': '1-2-3 Innings',
  CS: 'Caught Stealing',
  SAC: 'Sacrifice Bunt',
  SF: 'Sacrifice Fly',
  XBH: 'Extra-Base Hits',
  QAB: 'Quality At-Bats',
  'BA/RISP': 'Batting Average with Runners in Scoring Position',
  'C%': 'Contact Rate',
  'K%': 'Strikeout Rate',
  'BB%': 'Walk Rate',
  PCLL: 'Palm Coast Little League',
  SWOT: 'Strengths, Weaknesses, Opportunities, Threats',
  RSVP: 'Répondez S\'il Vous Plaît (Please Reply)',
  TBD: 'To Be Determined',
  SUB: 'Substitute / Borrowed Player',
};
