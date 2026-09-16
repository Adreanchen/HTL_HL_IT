# SEW 2026/27

## RESTful Webservice

Webservices bieten die Möglichkeit Dienste, die ein Server zu Verfügung stell anzusprechen. RESTful Webservices folgen den REST Grundprinzipien. 

Zu diesen zählen: Einfeutige Identifikation von Resourcen:

z.B.: https://shop.thlhl.at/products/67

Verwendung von http - Standardmethoden:

z.B.: GET, POST, PUT, PATCH, DELETE

Analogie objektorientierte Methodevs. RESTful Webservices

​	getUsers()	GET	https://shop.htlhl.at/users

​	updateUser(int id, User user)	PATCH	https://shop.thlhl.at/users/{id}

​	addUser(User user)	POST	https://shop.thlhl.at/users

​	deleteUser(ist id)	DELETE	https://shop.thlhl.at/users/{id}

Statuslose KOmmunikation:

Bei RESTful Webservices gibt es keinen Sitzungsstatus der serverseitig gespeichert wird. Stattdessen muss der Kommunikatiosnzustand im Client gespeichert werden.

​	Vorteile: Neustart des Servers, Skaliebarkeit

<img src="pics/https.png">
