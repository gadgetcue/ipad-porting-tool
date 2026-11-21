const { app, BrowserWindow, ipcMain, dialog, Menu } = require('electron');
const fs = require('fs');
const path = require('path');

const notesFile = () => path.join(app.getPath('userData'), 'notes.json');

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 700,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true },
  });
  win.loadFile('src/index.html');
}

ipcMain.handle('notes:load', async () => {
  try {
    return JSON.parse(fs.readFileSync(notesFile(), 'utf8'));
  } catch (e) {
    return [];
  }
});

ipcMain.handle('notes:save', async (_event, notes) => {
  fs.mkdirSync(path.dirname(notesFile()), { recursive: true });
  fs.writeFileSync(notesFile(), JSON.stringify(notes, null, 2));
  return true;
});

ipcMain.handle('notes:export', async (_event, text) => {
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath: 'notes.txt' });
  if (canceled || !filePath) return null;
  fs.writeFileSync(filePath, text);
  return filePath;
});

Menu.setApplicationMenu(Menu.buildFromTemplate([{ role: 'appMenu' }, { role: 'editMenu' }]));
app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
