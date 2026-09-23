package at.htlhl.httpclientdemo;

/**
 * POJO for product
 */
public class Product {

    // Fields *****************************************************************

    private int id;
    private String name;
    private String self_link;

    // Constructors ***********************************************************

    public Product() {

    }

    // Getters and Setters ****************************************************

    public int getId() {
        return id;
    }

    public void setId(int id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getSelf_link() {
        return self_link;
    }

    public void setSelf_link(String self_link) {
        this.self_link = self_link;
    }

    // toString für schöne Konsolenausgabe ************************************

    @Override
    public String toString() {
        return "Product{" +
                "id=" + id +
                ", name='" + name + '\'' +
                ", self_link='" + self_link + '\'' +
                '}';
    }
}