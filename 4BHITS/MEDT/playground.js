console.log("JS Array function startet ...");
fruits = ["Apfel", "Birne", "Apfel", "Banane", "Apfel", "Birne", "Orange", "Banane", "Apfel"];

console.log(fruits);

let counted = countWordsInArray(fruits);
console.log(JSON.parse(counted));

function countWordsInArray(array) {
    const result = {};
    array.forEach(function (element) {
        if (result[element]) {
            result[element]++;
        } else {
            result[element] = 1;
        }
    });
    return JSON.stringify(result, 2);
}
