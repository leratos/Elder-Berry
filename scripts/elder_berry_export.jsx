#target photoshop

var doc = app.activeDocument;
var exportPath = "C:\\Dev\\Elder-Berry\\src\\elder_berry\\avatar\\assets\\";

// Alle Ebenen unsichtbar
function hideAllLayers(layers) {
    for (var i = 0; i < layers.length; i++) {
        layers[i].visible = false;
        if (layers[i].typename === "LayerSet") {
            hideAllLayers(layers[i].layers);
        }
    }
}

// Elternpfad einer Ebene sichtbar schalten
function showParents(layer) {
    var parent = layer.parent;
    while (parent && parent.typename !== "Document") {
        parent.visible = true;
        parent = parent.parent;
    }
}

function exportLayer(layer) {
    hideAllLayers(doc.layers);

    // Ebene selbst + alle Eltern sichtbar
    layer.visible = true;
    showParents(layer);

    var fileName = layer.name.replace(/[^a-zA-Z0-9_-]/g, "_") + ".png";
    var filePath = new File(exportPath + fileName);

    var exportOptions = new ExportOptionsSaveForWeb();
    exportOptions.format = SaveDocumentType.PNG;
    exportOptions.PNG8 = false;
    exportOptions.transparency = true;

    doc.exportDocument(filePath, ExportType.SAVEFORWEB, exportOptions);
    $.writeln("Exportiert: " + fileName);
}

function processLayers(layers) {
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        if (layer.typename === "LayerSet") {
            processLayers(layer.layers);
        } else if (layer.typename === "ArtLayer") {
            exportLayer(layer);
        }
    }
}

// Originale Sichtbarkeit merken
var originalVisibility = [];
for (var i = 0; i < doc.layers.length; i++) {
    originalVisibility.push(doc.layers[i].visible);
}

processLayers(doc.layers);

// Wiederherstellen
for (var i = 0; i < doc.layers.length; i++) {
    doc.layers[i].visible = originalVisibility[i];
}

alert("Export abgeschlossen!\nDateien in: " + exportPath);
