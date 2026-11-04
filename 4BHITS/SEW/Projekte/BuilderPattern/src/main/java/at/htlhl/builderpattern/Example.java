package at.htlhl.builderpattern;

public class Example {
    static void main() {
        User user1 = new User.UserBuilder("Bart", "Simpson")
                .age(13)
                .phone("1234567")
                .address("Springfield?")
                .build();

        System.out.println(user1);


        User user2 = new User.UserBuilder("James", "Bond")
                .age(52)
                .phone("007")
                // no address
                .build();

        System.out.println(user2);


        User user3 = new User.UserBuilder("Super", "Man")
                // no age
                // no phone
                // no address
                .build();

        System.out.println(user3);
    }
}
