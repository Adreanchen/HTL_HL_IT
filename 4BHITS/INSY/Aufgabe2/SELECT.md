SELECT * FROM geschaeftsfuehrer;

SELECT name FROM arbeiter;

SELECT bezeichnung FROM fabrik WHERE geschaeftsfuehrer_id = 1;

SELECT * FROM aufgabe WHERE geschaeftsfuehrer_id = 2;

SELECT aufgaben_id FROM aufgabe_arbeiter WHERE arbeiter_id = 1001;

SELECT COUNT(*) FROM arbeiter;