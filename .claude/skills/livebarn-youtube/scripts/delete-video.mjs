// One-off: delete a video we uploaded. Uses the same cached OAuth token as the skill.
import fs from 'node:fs';
import path from 'node:path';
import { google } from 'googleapis';

const SECRETS = path.join(process.env.LOCALAPPDATA, 'livebarn-youtube', 'secrets');
const id = process.argv[2];
if (!id) { console.error('usage: node delete-video.mjs <videoId>'); process.exit(1); }

const cs = JSON.parse(fs.readFileSync(path.join(SECRETS, 'client_secret.json'), 'utf8'));
const c = cs.installed || cs.web;
const oauth = new google.auth.OAuth2(c.client_id, c.client_secret, 'http://127.0.0.1:8089/');
oauth.setCredentials(JSON.parse(fs.readFileSync(path.join(SECRETS, 'token.json'), 'utf8')));
const yt = google.youtube({ version: 'v3', auth: oauth });

const info = await yt.videos.list({ part: 'snippet', id });
const v = info.data.items?.[0];
if (!v) { console.error(`Video ${id} not found (already deleted?)`); process.exit(1); }
console.log(`Deleting "${v.snippet.title}" (${id})...`);
await yt.videos.delete({ id });
console.log('Deleted.');
