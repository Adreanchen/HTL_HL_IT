package at.htlhl.singletondemo;

public class SingletonDemo {

    public SingletonDemo() {
        int settingOne = ConfigAccessSingleton.getInstanze().readSettingOne();
        System.out.println("SettingOne is: " + settingOne);
    }

    static void main(String[] args) {
        new SingletonDemo();
    }
}
