/*
 * Example CTF Challenge - Simple Buffer Overflow
 * This is a basic example of a vulnerable program for CTF challenges
 *
 * Compile with: gcc -o challenge challenge.c -fno-stack-protector -no-pie
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void print_flag() {
    FILE *fp = fopen("flag.txt", "r");
    if (fp == NULL) {
        printf("Error: Could not open flag.txt\n");
        return;
    }

    char flag[256];
    if (fgets(flag, sizeof(flag), fp) != NULL) {
        printf("Congratulations! Here's your flag:\n%s\n", flag);
    }
    fclose(fp);
}

void vulnerable_function() {
    char buffer[64];

    printf("Welcome to the CTF challenge!\n");
    printf("Enter your input: ");
    fflush(stdout);

    // Vulnerable function - no bounds checking!
    gets(buffer);

    printf("You entered: %s\n", buffer);
}

int main() {
    // Disable buffering
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stdin, NULL, _IONBF, 0);

    vulnerable_function();

    printf("Thanks for playing!\n");
    return 0;
}
