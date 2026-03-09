import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Paths
const sourceDir = path.resolve(__dirname, '../../data/sharks');
const destDir = path.resolve(__dirname, '../public/data');

// Ensure destination exists
if (!fs.existsSync(destDir)) {
  fs.mkdirSync(destDir, { recursive: true });
}

// Files to copy
const filesToSync = [
  'team.json',
  'swot_analysis.json',
  'lineups.json'
];

console.log('Syncing GameChanger data to client/public/data...');

filesToSync.forEach(file => {
  const src = path.join(sourceDir, file);
  const dest = path.join(destDir, file);
  
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
    console.log(`✅ Synced ${file}`);
  } else {
    console.warn(`⚠️ Warning: Source file not found: ${src}`);
  }
});

console.log('Data sync complete.');
