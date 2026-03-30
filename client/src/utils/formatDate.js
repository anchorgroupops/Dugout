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

/** Stat tooltip abbreviation map — complete glossary for all 185+ GameChanger stats */
export const STAT_GLOSSARY = {
  // ===== BATTING STANDARD =====
  GP: 'Games Played',
  PA: 'Plate Appearances',
  AB: 'At Bats',
  AVG: 'Batting Average (H/AB)',
  OBP: 'On-Base Percentage',
  OPS: 'On-Base + Slugging',
  SLG: 'Slugging Percentage (TB/AB)',
  H: 'Hits',
  '1B': 'Singles',
  '2B': 'Doubles',
  '3B': 'Triples',
  HR: 'Home Runs',
  RBI: 'Runs Batted In',
  R: 'Runs Scored',
  BB: 'Walks (Base on Balls)',
  HBP: 'Hit By Pitch',
  ROE: 'Reached On Error',
  FC: "Fielder's Choice",
  CI: "Catcher's Interference",
  SAC: 'Sacrifice (Bunt)',
  SF: 'Sacrifice Fly',
  SO: 'Strikeouts',
  'K-L': 'Strikeouts Looking',
  SB: 'Stolen Bases',
  CS: 'Caught Stealing',
  'SB%': 'Stolen Base Percentage',
  PIK: 'Picked Off',

  // ===== BATTING ADVANCED =====
  TB: 'Total Bases',
  XBH: 'Extra Base Hits (2B+3B+HR)',
  'AB/HR': 'At Bats Per Home Run',
  'BA/RISP': 'Batting Avg with Runners in Scoring Position',
  BABIP: 'Batting Avg on Balls in Play',
  PS: 'Pitches Seen',
  'PS/PA': 'Pitches Seen Per Plate Appearance',
  QAB: 'Quality At Bats',
  'QAB%': 'Quality At Bat Percentage',
  'BB/K': 'Walk to Strikeout Ratio',
  'C%': 'Contact Percentage',
  '2OUTRBI': 'Two-Out RBI',
  HHB: 'Hard Hit Balls',
  GIDP: 'Grounded Into Double Play',
  GITP: 'Grounded Into Triple Play',
  '6+': 'Plate Appearances with 6+ Pitches',
  '6+%': 'Percentage of PA with 6+ Pitches',
  '2S+3': 'Hits After 2 Strikes with 3+ Pitches',
  '2S+3%': 'Rate of Hits After 2-Strike Counts',
  'FB%': 'Fly Ball Percentage',
  'GB%': 'Ground Ball Percentage',
  'LD%': 'Line Drive Percentage',

  // ===== PITCHING STANDARD =====
  GS: 'Games Started',
  W: 'Wins',
  L: 'Losses',
  SV: 'Saves',
  SVO: 'Save Opportunities',
  'SV%': 'Save Percentage',
  IP: 'Innings Pitched',
  ER: 'Earned Runs',
  ERA: 'Earned Run Average (ER*7/IP for softball)',
  WHIP: 'Walks + Hits per Inning Pitched',
  BAA: 'Batting Average Against',
  BF: 'Batters Faced',
  '#P': 'Number of Pitches Thrown',
  KL: 'Strikeouts Looking (Pitching)',
  WP: 'Wild Pitches',
  BK: 'Balks',
  LOB: 'Left on Base',
  'W-L': 'Win-Loss Record',

  // ===== PITCHING ADVANCED =====
  'S%': 'Strike Percentage',
  'P/IP': 'Pitches Per Inning',
  'P/BF': 'Pitches Per Batter Faced',
  'FPS%': 'First Pitch Strike Percentage',
  'FPSW%': 'First Pitch Strike — Walk Rate',
  'FPSO%': 'First Pitch Strike — Strikeout Rate',
  'FPSH%': 'First Pitch Strike — Hit Rate',
  '<3%': 'Under 3-Pitch At Bats Percentage',
  '1ST2OUT': 'First Batter Gets 2 Outs',
  '123INN': '1-2-3 Innings (All 3 Batters Retired)',
  '0BBINN': 'Zero Walk Innings',
  LOO: 'Lead-Off Outs',
  FIP: 'Fielding Independent Pitching',
  'K/BF': 'Strikeout Rate (K per Batter Faced)',
  'K/BB': 'Strikeout to Walk Ratio',
  'BB/INN': 'Walks Per Inning',
  'GO/AO': 'Ground Out to Air Out Ratio',
  'HHB%': 'Hard Hit Ball Percentage (Against)',
  'WEAK%': 'Weak Contact Percentage',
  'SM%': 'Swing and Miss Percentage',

  // ===== PITCHING BREAKDOWN (Pitch Arsenal) =====
  FB: 'Fastball Count',
  CH: 'Change-Up Count',
  CB: 'Curveball Count',
  SC: 'Slider/Cutter Count',
  RB: 'Riseball Count',
  DB: 'Dropball Count',
  DC: 'Drop Curve Count',
  KB: 'Knuckleball Count',
  KC: 'Knuckle Curve Count',
  OS: 'Off-Speed Pitch Count',
  MPH: 'Average Velocity (MPH)',
  'SW%': 'Swinging Strike Rate',

  // ===== FIELDING STANDARD =====
  TC: 'Total Chances',
  PO: 'Putouts',
  A: 'Assists',
  E: 'Errors',
  FPCT: 'Fielding Percentage (PO+A)/(PO+A+E)',
  DP: 'Double Plays Turned',
  TP: 'Triple Plays Turned',

  // ===== CATCHING =====
  INN: 'Innings Caught',
  'CS%': 'Caught Stealing Percentage',
  'SB-ATT': 'Stolen Bases — Attempts',
  PB: 'Passed Balls',

  // ===== INNINGS PLAYED =====
  Total: 'Total Innings Played (All Positions)',
  P: 'Innings at Pitcher',
  C: 'Innings at Catcher',
  SS: 'Innings at Shortstop',
  LF: 'Innings in Left Field',
  CF: 'Innings in Center Field',
  RF: 'Innings in Right Field',

  // ===== OTHER =====
  K: 'Strikeouts',
  NP: 'Number of Pitches',
  'K%': 'Strikeout Rate',
  'BB%': 'Walk Rate',
  PCLL: 'Palm Coast Little League',
  SWOT: 'Strengths, Weaknesses, Opportunities, Threats',
  RSVP: 'R\u00e9pondez S\'il Vous Pla\u00eet (Please Reply)',
  TBD: 'To Be Determined',
  SUB: 'Substitute / Borrowed Player',
};
