const fs=require('node:fs'),path=require('node:path');
exports.readUI=()=>fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8').replace('<link rel="stylesheet" href="/styles.css">','<style>'+fs.readFileSync(path.join(__dirname,'..','styles.css'),'utf8')+'</style>');
