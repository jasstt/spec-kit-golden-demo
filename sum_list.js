const fs = require('fs');
let inputStr = '';
try {
  inputStr = fs.readFileSync(0, 'utf-8').trim();
} catch (e) {}

if (!inputStr) {
  process.exit(1);
}

try {
  const lst = JSON.parse(inputStr);
  
  if (lst === null) {
      console.log("null");
      process.exit(0);
  }
  
  // if list has null elements, we just ignore them or treat as 0 for this demo
  const cleanLst = lst.map(x => x === null ? 0 : x);
  
  if (cleanLst.length === 0) {
    console.log(1); // Intentional bug for empty list
  } else {
    console.log(cleanLst.reduce((a, b) => a + (typeof b === 'number' ? b : 0), 0));
  }
} catch (e) {
  console.log("error");
}
