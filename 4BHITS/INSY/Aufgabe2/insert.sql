DROP TABLE IF EXISTS aufgabe_arbeiter CASCADE;
DROP TABLE IF EXISTS arbeiter CASCADE;
DROP TABLE IF EXISTS aufgabe CASCADE;
DROP TABLE IF EXISTS fabrik CASCADE;
DROP TABLE IF EXISTS geschaeftsfuehrer CASCADE;

CREATE TABLE geschaeftsfuehrer (
    geschaeftsfuehrer_id INT PRIMARY KEY,
    name VARCHAR(45) NOT NULL
);

CREATE TABLE fabrik (
    fabrik_id INT PRIMARY KEY,
    bezeichnung VARCHAR(45) NOT NULL,
    geschaeftsfuehrer_id INT UNIQUE,
    CONSTRAINT fk_fabrik_gf FOREIGN KEY (geschaeftsfuehrer_id)
        REFERENCES geschaeftsfuehrer(geschaeftsfuehrer_id) ON DELETE SET NULL
);

CREATE TABLE aufgabe (
    aufgaben_id INT PRIMARY KEY,
    bezeichnung VARCHAR(45) NOT NULL,
    geschaeftsfuehrer_id INT,
    CONSTRAINT fk_aufgabe_gf FOREIGN KEY (geschaeftsfuehrer_id)
        REFERENCES geschaeftsfuehrer(geschaeftsfuehrer_id) ON DELETE SET NULL
);

CREATE TABLE arbeiter (
    arbeiter_id INT PRIMARY KEY,
    name VARCHAR(45) NOT NULL,
    fabrik_id INT,
    CONSTRAINT fk_arbeiter_fabrik FOREIGN KEY (fabrik_id)
        REFERENCES fabrik(fabrik_id) ON DELETE SET NULL
);

CREATE TABLE aufgabe_arbeiter (
    arbeiter_id INT,
    aufgaben_id INT,
    PRIMARY KEY (arbeiter_id, aufgaben_id),
    CONSTRAINT fk_aa_arbeiter FOREIGN KEY (arbeiter_id)
        REFERENCES arbeiter(arbeiter_id) ON DELETE CASCADE,
    CONSTRAINT fk_aa_aufgabe FOREIGN KEY (aufgaben_id)
        REFERENCES aufgabe(aufgaben_id) ON DELETE CASCADE
);

INSERT INTO geschaeftsfuehrer (geschaeftsfuehrer_id, name) VALUES
(1, 'Dr. Sarah Connor'),
(2, 'Thomas Meier'),
(3, 'Sabine Huber');

INSERT INTO fabrik (fabrik_id, bezeichnung, geschaeftsfuehrer_id) VALUES
(10, 'Werk Nord (Linz)', 1),
(20, 'Werk Süd (Graz)', 2),
(30, 'Werk Ost (Wien)', 3);

INSERT INTO aufgabe (aufgaben_id, bezeichnung, geschaeftsfuehrer_id) VALUES
(101, 'Sicherheitsaudit durchführen', 1),
(102, 'Produktionslinie kalibrieren', 1),
(103, 'Wartung Förderband', 2),
(104, 'Materialeingang prüfen', 2),
(105, 'Brandschutzübung vorbereiten', 3);

INSERT INTO arbeiter (arbeiter_id, name, fabrik_id) VALUES
(1001, 'Florian Bauer', 10),
(1002, 'Julia Wagner', 10),
(1003, 'Maximilian Koch', 20),
(1004, 'Sophie Pichler', 20),
(1005, 'Lukas Gruber', 30);

INSERT INTO aufgabe_arbeiter (arbeiter_id, aufgaben_id) VALUES
(1001, 101),
(1001, 102),
(1002, 102),
(1003, 103),
(1004, 103),
(1004, 104),
(1005, 105);