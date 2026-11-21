/*
 * The Electron main-process handlers of this example, ported for iPad / iPhone.
 * ipadport copies this file into the generated project instead of generating stubs.
 */
(function () {
  'use strict';
  var ipadport = window.ipadport;
  var fs = ipadport.fs, path = ipadport.path;
  var app = ipadport.electron.app;
  var notesFile = function () { return path.join(app.getPath('userData'), 'notes.json'); };

  window.ipadportHandlers = Object.assign(window.ipadportHandlers || {}, {
    'notes:load': function () {
      try {
        return JSON.parse(fs.readFileSync(notesFile(), 'utf8'));
      } catch (e) {
        return [];
      }
    },
    'notes:save': function (notes) {
      fs.mkdirSync(path.dirname(notesFile()), { recursive: true });
      fs.writeFileSync(notesFile(), JSON.stringify(notes, null, 2));
      return true;
    },
    'notes:export': function (text) {
      return ipadport.electron.dialog.showSaveDialog({ defaultPath: 'notes.txt' }).then(function (res) {
        if (res.canceled || !res.filePath) return null;
        fs.writeFileSync(res.filePath, text);
        ipadport.share({ path: res.filePath });
        return res.filePath;
      });
    }
  });
})();
