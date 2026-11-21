const { contextBridge, ipcRenderer, shell } = require('electron');

contextBridge.exposeInMainWorld('notesApi', {
  load: () => ipcRenderer.invoke('notes:load'),
  save: (notes) => ipcRenderer.invoke('notes:save', notes),
  exportText: (text) => ipcRenderer.invoke('notes:export', text),
  openHelp: () => shell.openExternal('https://github.com/gadgetcue/ipad-porting-tool'),
});
