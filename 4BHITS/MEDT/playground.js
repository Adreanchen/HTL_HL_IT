console.log("JS Array function startet ...");
fruits = ["Apfel", "Birne", "Apfel", "Banane", "Apfel", "Birne", "Orange", "Banane", "Apfel"];

console.log(fruits);

let counted = countWordsInArray(fruits);
console.log(JSON.parse(counted));

function countWordsInArray(array) {
    const result = {};
    array.forEach(
        function (element) {
            if (result[element]) {
                result[element]++;
            } else {
                result[element] = 1;
            }
        });
    return JSON.stringify(result, 2);
}


numbers = [13, 43, 12, 21, 21, 21, 2, 3, 34, 4, 3, 43, 5, 6, 67, 7, 68, 7, 8, 89, 8];
numbers2 = [1, 1, 1];

function sum(numbers) {
    return numbers.reduce((acc, current) => acc + current);
}

console.log(sum(numbers));
console.log(numbers2.reduce((acc, current) => acc + current));


const users = ["Lia", "Jim", "Mia", "Tim", "Pia", "Wim", "Bea", "Tom", "Gia", "Sam"];

const fetchData = async () => {
    try {
        const todos = await fetch("https://jsonplaceholder.typicode.com/todos"); const response = await todos.json();

        // TODO 1:                 



        // TODO 2:             

        console.log(newArray)
    } catch (error) { console.log(error); }
};

fetchData();
