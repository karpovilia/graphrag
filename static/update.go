package main

import (
	"errors"
	"fmt"
	"os"
	"path"
	"strings"
)

func WrapError(message string, err error) error {
	if err != nil {
		return fmt.Errorf(message+": %w", err)

	}

	return errors.New(message)

}

func CreateNew() error {
	dir, err := os.ReadDir(".")
	if err != nil {
		return WrapError("read current dir", err)
	}

	for _, file := range dir {
		if !strings.Contains(file.Name(), ".json") {
			continue
		}
		newDir := strings.Replace(file.Name(), ".json", "", 1)
		newFilePath := path.Join(newDir, "graph.json")

		fileByte, err := os.ReadFile(file.Name())
		if err != nil {
			return WrapError(fmt.Sprintf("read file: %s", file.Name()), err)
		}
		err = os.MkdirAll(newDir, 0777)
		if err != nil {
			return WrapError(fmt.Sprintf("create dir: %s", newDir), err)
		}
		newFile, err := os.Create(newFilePath)
		if err != nil {
			return WrapError(fmt.Sprintf("create file: %s", newFilePath), err)

		}
		_, err = newFile.Write(fileByte)
		if err != nil {
			return WrapError(fmt.Sprintf("write file: %s", newFilePath), err)

		}

	}

	return nil
}

func main() {
	err := CreateNew()
	if err != nil {
		panic(err)
	}

	fmt.Println("success")

}
